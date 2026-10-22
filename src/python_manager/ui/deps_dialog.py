"""Dialog showing what a package requires and what requires it."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QListWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ..core import deps


class DependencyDialog(QDialog):
    def __init__(self, graph: deps.Graph, name: str, parent=None):
        super().__init__(parent)
        self.graph = graph
        key = deps.normalize(name)
        dist = graph.get(key)
        self.setWindowTitle(f"Dependencies of {dist.name if dist else name}")
        self.resize(720, 480)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Package", "Version"])
        self.tree.setColumnWidth(0, 300)
        if dist:
            for req in dist.requires:
                self.tree.addTopLevelItem(self._item(req, {key}))
        requires_box = QGroupBox(f"Requires ({len(dist.requires) if dist else 0})")
        QVBoxLayout(requires_box).addWidget(self.tree)

        users = deps.required_by(graph).get(key, [])
        self.users = QListWidget()
        self.users.addItems(users)
        users_box = QGroupBox(f"Required by ({len(users)})")
        QVBoxLayout(users_box).addWidget(self.users)

        row = QHBoxLayout()
        row.addWidget(requires_box, 3)
        row.addWidget(users_box, 2)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(buttons)

    def _item(self, key: str, path: set[str]) -> QTreeWidgetItem:
        """Tree node for ``key``; ``path`` holds its ancestors to stop at cycles."""
        dist = self.graph.get(key)
        if dist is None:
            return QTreeWidgetItem([key, "not installed"])
        if key in path:
            return QTreeWidgetItem([dist.name, f"{dist.version} (cycle)"])
        item = QTreeWidgetItem([dist.name, dist.version])
        for req in dist.requires:
            item.addChild(self._item(req, path | {key}))
        return item
