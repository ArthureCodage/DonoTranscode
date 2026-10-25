"""Création de champs et lecture / écriture automatique des réglages d'un onglet."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QLineEdit, QSpinBox)


def combo(items, default=None, editable=False) -> QComboBox:
    c = QComboBox()
    c.setEditable(editable)
    for it in items:
        if isinstance(it, tuple):
            c.addItem(it[1], it[0])
        else:
            c.addItem(str(it), it)
    if default is not None:
        set_value(c, default)
    return c


def spin(lo, hi, val, suffix="", step=1, special="") -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(val)
    s.setSingleStep(step)
    if suffix:
        s.setSuffix(suffix)
    if special:
        s.setSpecialValueText(special)
    return s


def dspin(lo, hi, val, decimals=2, suffix="", step=0.1, special="") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setValue(val)
    s.setSingleStep(step)
    if suffix:
        s.setSuffix(suffix)
    if special:
        s.setSpecialValueText(special)
    return s


def check(text, val=False) -> QCheckBox:
    c = QCheckBox(text)
    c.setChecked(val)
    return c


def line(text="", placeholder="") -> QLineEdit:
    e = QLineEdit(text)
    e.setPlaceholderText(placeholder)
    return e


def form_group(title: str) -> tuple[QGroupBox, QFormLayout]:
    g = QGroupBox(title)
    f = QFormLayout(g)
    f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    return g, f


def get_value(w):
    if isinstance(w, QComboBox):
        if w.isEditable():
            i = w.findText(w.currentText())
            return w.itemData(i) if i >= 0 and w.itemData(i) is not None else w.currentText()
        d = w.currentData()
        return d if d is not None else w.currentText()
    if isinstance(w, (QSpinBox, QDoubleSpinBox)):
        return w.value()
    if isinstance(w, QCheckBox):
        return w.isChecked()
    if isinstance(w, QLineEdit):
        return w.text()
    if isinstance(w, QGroupBox):
        return w.isChecked()
    raise TypeError(type(w))


def set_value(w, v):
    if isinstance(w, QComboBox):
        i = w.findData(v)
        if i < 0:
            i = w.findText(str(v))
        if i >= 0:
            w.setCurrentIndex(i)
        elif w.isEditable():
            w.setEditText(str(v))
    elif isinstance(w, QSpinBox):
        w.setValue(int(v))
    elif isinstance(w, QDoubleSpinBox):
        w.setValue(float(v))
    elif isinstance(w, (QCheckBox, QGroupBox)):
        w.setChecked(bool(v))
    elif isinstance(w, QLineEdit):
        w.setText(str(v))


def change_signals(w):
    if isinstance(w, QComboBox):
        sig = [w.currentIndexChanged]
        if w.isEditable():
            sig.append(w.editTextChanged)
        return sig
    if isinstance(w, (QSpinBox, QDoubleSpinBox)):
        return [w.valueChanged]
    if isinstance(w, (QCheckBox, QGroupBox)):
        return [w.toggled]
    if isinstance(w, QLineEdit):
        return [w.textChanged]
    return []


class Binder:
    """Associe des clés à des champs pour sauver / recharger tous les réglages d'un coup."""

    def __init__(self):
        self.widgets: dict[str, object] = {}

    def add(self, key: str, widget):
        self.widgets[key] = widget
        return widget

    def __getitem__(self, key):
        return get_value(self.widgets[key])

    def get(self) -> dict:
        return {k: get_value(w) for k, w in self.widgets.items()}

    def set(self, data: dict):
        for k, w in self.widgets.items():
            if k in data:
                try:
                    set_value(w, data[k])
                except (TypeError, ValueError):
                    pass

    def on_change(self, callback):
        for w in self.widgets.values():
            for sig in change_signals(w):
                sig.connect(lambda *_: callback())
