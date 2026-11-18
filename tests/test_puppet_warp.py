# SPDX-License-Identifier: Apache-2.0
import numpy as np
from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QColor, QPainter

from photoslop import npimage
from photoslop.document import Document
from photoslop.layer import blank_image
from photoslop.mainwindow import MainWindow
from photoslop.puppet import PuppetPin, compute_triangle_depths, generate_mesh, solve_arap


def stripe_image(w=80, h=80):
    img = blank_image(QSize(w, h))
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.fillRect(QRect(38, 0, 4, h), QColor(255, 0, 0))  # vertical red stripe
    p.end()
    return img


def stripe_x(img, y) -> int:
    for x in range(img.width()):
        c = img.pixelColor(x, y)
        if c.red() > 200 and c.green() < 80:
            return x
    return -1


def test_puppet_warp_bends_around_anchors(qapp):
    img = stripe_image()
    pins = [
        ((40, 5), (40, 5)),  # anchor top
        ((40, 75), (40, 75)),  # anchor bottom
        ((40, 40), (55, 40)),
    ]  # middle pulled right
    warped = npimage.puppet_warp(img, pins)
    assert stripe_x(warped, 40) > 46  # middle bent right
    assert abs(stripe_x(warped, 5) - 38) <= 3  # anchored ends stay put
    assert abs(stripe_x(warped, 75) - 38) <= 3


def test_puppet_tool_session_commit_cancel(qapp):
    win = MainWindow()
    doc = Document.new(QSize(80, 80), 72.0, "pw", QColor(255, 255, 255))
    doc.layers[0].image = stripe_image()
    win.add_document(doc)
    editor = win.current_editor()
    tool = win.tools["puppet"]

    tool.press(doc, editor.canvas, QPointF(40, 5), None)  # anchor
    tool.press(doc, editor.canvas, QPointF(40, 75), None)  # anchor
    tool.press(doc, editor.canvas, QPointF(40, 40), None)  # pin to drag
    tool.press(doc, editor.canvas, QPointF(40, 40), None)  # grab it
    assert tool._drag == 2
    tool.move(doc, editor.canvas, QPointF(55, 40), None)
    tool.release(doc, editor.canvas, QPointF(55, 40), None)

    assert stripe_x(doc.active_layer.image, 40) > 46  # live warp applied
    tool.commit(editor.canvas)
    assert doc.undo_stack.command(0).text() == "Puppet Warp"
    doc.undo_stack.undo()
    assert stripe_x(doc.active_layer.image, 40) == 38  # exact restore

    tool.press(doc, editor.canvas, QPointF(40, 40), None)  # new session
    tool.press(doc, editor.canvas, QPointF(40, 40), None)
    tool.move(doc, editor.canvas, QPointF(60, 40), None)
    tool.cancel(doc)
    assert stripe_x(doc.active_layer.image, 40) == 38
    assert doc.undo_stack.count() == 1  # cancel pushed nothing new


def test_generate_mesh_covers_alpha(qapp):
    img = blank_image(QSize(100, 100))
    img.fill(0)  # transparent
    p = QPainter(img)
    p.fillRect(QRect(30, 30, 40, 40), QColor(0, 0, 255, 255))  # 40x40 square in center
    p.end()

    mesh = generate_mesh(img, spacing=10)
    assert len(mesh.vertices) > 0
    assert len(mesh.triangles) > 0
    # Vertices should be concentrated around [20, 80] due to dilation margin,
    # and strictly not covering corners like (0,0) or (99,99)
    assert np.min(mesh.vertices[:, 0]) >= 20
    assert np.max(mesh.vertices[:, 0]) <= 80
    assert np.min(mesh.vertices[:, 1]) >= 20
    assert np.max(mesh.vertices[:, 1]) <= 80


def test_arap_modes_rigid_normal_distort(qapp):
    img = stripe_image(100, 100)
    mesh_rigid = generate_mesh(img, spacing=15)
    mesh_distort = generate_mesh(img, spacing=15)

    pins_rigid = [
        PuppetPin(np.array([20.0, 50.0]), np.array([20.0, 50.0])),
        PuppetPin(np.array([80.0, 50.0]), np.array([110.0, 50.0])),  # stretch by 30px
    ]
    pins_distort = [
        PuppetPin(np.array([20.0, 50.0]), np.array([20.0, 50.0])),
        PuppetPin(np.array([80.0, 50.0]), np.array([110.0, 50.0])),
    ]

    solve_arap(mesh_rigid, pins_rigid, mode="rigid")
    solve_arap(mesh_distort, pins_distort, mode="distort")

    # In distort mode, elements stretch more freely along the pin vector
    mid_rigid = mesh_rigid.deformed_vertices[:, 0]
    mid_distort = mesh_distort.deformed_vertices[:, 0]
    assert np.max(mid_rigid) > 100.0
    assert np.max(mid_distort) > 100.0


def test_pin_rotation(qapp):
    img = stripe_image(100, 100)
    mesh = generate_mesh(img, spacing=15)
    # Anchor pin at (20, 50), pin at (80, 50) rotated by 90 degrees
    p_anchor = PuppetPin(np.array([20.0, 50.0]), np.array([20.0, 50.0]))
    p_rotated = PuppetPin(np.array([80.0, 50.0]), np.array([80.0, 50.0]), rotation=90.0)

    solve_arap(mesh, [p_anchor, p_rotated], mode="normal")
    # Vertices near (80, 50) should have shifted in y due to 90 degree rotation
    v_def = mesh.deformed_vertices
    v_rest = mesh.vertices
    dists = np.hypot(v_rest[:, 0] - 80.0, v_rest[:, 1] - 50.0)
    nbr_idx = np.where((dists > 5.0) & (dists < 25.0))[0]
    y_shifts = np.abs(v_def[nbr_idx, 1] - v_rest[nbr_idx, 1])
    assert np.max(y_shifts) > 1.0


def test_depth_pinning_overlap_order(qapp):
    img = stripe_image(100, 100)
    mesh = generate_mesh(img, spacing=15)
    p_back = PuppetPin(np.array([20.0, 20.0]), np.array([20.0, 20.0]), depth=-2)
    p_front = PuppetPin(np.array([80.0, 80.0]), np.array([80.0, 80.0]), depth=3)

    depths = compute_triangle_depths(mesh, [p_back, p_front])
    assert -2 in depths
    assert 3 in depths


def test_mainwindow_action_puppet_warp(qapp):
    win = MainWindow()
    doc = Document.new(QSize(80, 80), 72.0, "pw", QColor(255, 255, 255))
    doc.layers[0].image = stripe_image()
    win.add_document(doc)

    # Trigger action
    win.action_puppet_warp()
    tool = win.tools["puppet"]
    assert tool.session is not None
    assert tool.session.mode == "normal"

    # Change mode and density
    win._on_puppet_mode_changed("Rigid")
    assert tool.session.mode == "rigid"
    win._on_puppet_density_changed("Low")
    assert tool.session.density == "low"

    # Add a pin
    editor = win.current_editor()
    tool.press(doc, editor.canvas, QPointF(40, 40), None)
    assert len(tool.session.pins) == 1

    # Depth adjustment
    win._on_puppet_depth_changed(+1)
    assert tool.session.pins[0].depth == 1

    # Commit
    win._on_puppet_commit()
    assert tool.session is None
    assert doc.undo_stack.count() == 1
