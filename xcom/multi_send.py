"""多条发送：标签分组，标签内分页（每页 10 条、左右两列），"+"号加标签，右键管理，持久化。"""

from __future__ import annotations

import configparser
import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QGridLayout, QHBoxLayout, QVBoxLayout, QCheckBox,
    QLineEdit, QPushButton, QLabel, QSpinBox, QTabWidget,
    QInputDialog, QMessageBox, QMenu, QGroupBox, QDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QAbstractItemView,
)

from .paths import app_dir

ENTRIES_PER_PAGE = 10
ROWS_PER_COLUMN = 5
ENTRY_BUTTON_WIDTH = 36  # 最多容纳 3 位序号，把水平空间优先留给命令内容
CONFIG_PATH = app_dir() / "xcom_multisend.json"


def _empty_item():
    return {"hex": False, "text": "", "desc": ""}


def _empty_page():
    return [_empty_item() for _ in range(ENTRIES_PER_PAGE)]


class TagPage(QWidget):
    """单个标签：多页命令，每页 10 条（左右两列各 5 条），带页操作栏。"""

    def __init__(self, send_entry_func, on_changed, tag_name="", parent=None):
        super().__init__(parent)
        self._on_changed = on_changed
        self.tag_name = tag_name
        self._loading = False
        self.pages = [_empty_page()]
        self.current = 0
        self.entries = []   # [(hex_chk, line_edit), ...] 当前页 10 条
        self._send_btns = []

        grid = QGridLayout()
        grid.setContentsMargins(2, 2, 2, 1)
        grid.setHorizontalSpacing(3)
        grid.setVerticalSpacing(2)
        for col in range(2):
            base_col = col * 4
            grid.addWidget(QLabel("HEX"), 0, base_col, alignment=Qt.AlignCenter)
            grid.addWidget(QLabel("内容"), 0, base_col + 1)
            grid.setColumnStretch(base_col + 1, 1)
            for row in range(ROWS_PER_COLUMN):
                idx = col * ROWS_PER_COLUMN + row
                hex_chk = QCheckBox()
                hex_chk.toggled.connect(
                    lambda _=False, i=idx: self._entry_changed(i, save=True))
                edit = QLineEdit()
                edit.textChanged.connect(
                    lambda _="", i=idx: self._entry_changed(i, save=True))
                edit.editingFinished.connect(self._on_changed)
                btn = QPushButton()
                btn.setFixedWidth(ENTRY_BUTTON_WIDTH)
                btn.clicked.connect(lambda _=False, i=idx: send_entry_func(i))
                grid.addWidget(hex_chk, row + 1, base_col, alignment=Qt.AlignCenter)
                grid.addWidget(edit, row + 1, base_col + 1)
                grid.addWidget(btn, row + 1, base_col + 2)
                self.entries.append((hex_chk, edit))
                self._send_btns.append(btn)
            if col == 0:
                grid.setColumnMinimumWidth(3, 8)  # 两列之间仅保留必要间隔
        grid.setRowStretch(ROWS_PER_COLUMN + 1, 1)  # 内容顶部对齐

        # 页操作栏
        self.page_label = QLabel()
        remove_btn = QPushButton("移除此页")
        remove_btn.clicked.connect(self.remove_page)
        add_btn = QPushButton("添加页")
        add_btn.clicked.connect(self.add_page)
        first_btn = QPushButton("首页")
        first_btn.clicked.connect(lambda: self.goto_page(0))
        prev_btn = QPushButton("上一页")
        prev_btn.clicked.connect(lambda: self.goto_page(self.current - 1))
        next_btn = QPushButton("下一页")
        next_btn.clicked.connect(lambda: self.goto_page(self.current + 1))
        last_btn = QPushButton("尾页")
        last_btn.clicked.connect(lambda: self.goto_page(len(self.pages) - 1))
        self.jump_spin = QSpinBox()
        self.jump_spin.setRange(1, 1)
        jump_btn = QPushButton("跳转")
        jump_btn.clicked.connect(
            lambda: self.goto_page(self.jump_spin.value() - 1))
        edit_btn = QPushButton("编辑条目")
        edit_btn.clicked.connect(self.edit_entries)

        page_bar = QHBoxLayout()
        page_bar.setSpacing(3)
        page_bar.addWidget(self.page_label)
        for w in (remove_btn, add_btn, first_btn, prev_btn, next_btn, last_btn):
            page_bar.addWidget(w)
        page_bar.addWidget(QLabel("页码"))
        page_bar.addWidget(self.jump_spin)
        page_bar.addWidget(jump_btn)
        page_bar.addStretch()
        page_bar.addWidget(edit_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(3)
        layout.addLayout(grid)
        layout.addLayout(page_bar)

        self._show_page(0)

    # ---------- 页内条目 ----------

    def _entry_changed(self, idx, save=False):
        if self._loading:
            return
        chk, edit = self.entries[idx]
        item = self.pages[self.current][idx]  # 原地更新以保留 desc 字段
        item["hex"] = chk.isChecked()
        item["text"] = edit.text()
        if save:
            self._on_changed()

    # ---------- 翻页 ----------

    def _show_page(self, idx: int):
        idx = max(0, min(idx, len(self.pages) - 1))
        self.current = idx
        self._loading = True
        for i, (chk, edit) in enumerate(self.entries):
            item = self.pages[idx][i]
            chk.setChecked(bool(item.get("hex")))
            edit.setText(str(item.get("text", "")))
            edit.setToolTip(str(item.get("desc", "")))  # 描述作悬停提示
            self._send_btns[i].setText(str(idx * ENTRIES_PER_PAGE + i + 1))
        self._loading = False
        self.page_label.setText(f"页码 {idx + 1}/{len(self.pages)}")
        self.jump_spin.setMaximum(len(self.pages))

    def goto_page(self, idx: int):
        self._show_page(idx)

    def add_page(self):
        self.pages.append(_empty_page())
        self._show_page(len(self.pages) - 1)
        self._on_changed()

    def remove_page(self):
        has_content = any(item["text"] for item in self.pages[self.current])
        if has_content and QMessageBox.question(
                self, "移除此页",
                f"第 {self.current + 1} 页有命令，确认移除？") != QMessageBox.Yes:
            return
        if len(self.pages) == 1:
            self.pages[0] = _empty_page()
        else:
            del self.pages[self.current]
        self._show_page(self.current)
        self._on_changed()

    # ---------- 数据 ----------

    def to_data(self):
        return self.pages

    def load_data(self, pages):
        clean = []
        for pg in pages if isinstance(pages, list) else []:
            if not isinstance(pg, list):
                continue
            items = []
            for it in pg[:ENTRIES_PER_PAGE]:
                it = it if isinstance(it, dict) else {}
                items.append({"hex": bool(it.get("hex")),
                              "text": str(it.get("text", "")),
                              "desc": str(it.get("desc", ""))})
            while len(items) < ENTRIES_PER_PAGE:
                items.append(_empty_item())
            clean.append(items)
        self.pages = clean or [_empty_page()]
        self._show_page(0)

    def all_items(self):
        """当前标签全部命令（跨页展平）的副本。"""
        return [dict(it) for pg in self.pages for it in pg]

    def set_all_items(self, items):
        """用展平列表覆盖当前标签，按每页 10 条重新切分。"""
        items = [dict(it) for it in items] or [_empty_item()]
        while len(items) % ENTRIES_PER_PAGE != 0:
            items.append(_empty_item())
        self.pages = [items[i:i + ENTRIES_PER_PAGE]
                      for i in range(0, len(items), ENTRIES_PER_PAGE)]
        self._show_page(min(self.current, len(self.pages) - 1))

    def edit_entries(self):
        dlg = EntryEditorDialog(self.tag_name, self.all_items(), self)
        if dlg.exec() == QDialog.Accepted:
            self.set_all_items(dlg.result_items())
            self._on_changed()


class MultiSendPage(QWidget):
    """send_func(text, is_hex, newline) 由主窗口提供，负责实际发送。

    标签栏最后固定一个 "+" 页签用于添加标签；
    右键页签弹出重命名/删除菜单，双击页签直接重命名。
    """

    def __init__(self, send_func, parent=None):
        super().__init__(parent)
        self._send_func = send_func
        self._cycle_index = 0
        self._prev_index = 0
        self._tick_busy = False

        self.tag_tabs = QTabWidget()
        self.tag_tabs.tabBarClicked.connect(self._on_tab_clicked)
        self.tag_tabs.tabBarDoubleClicked.connect(self._on_tab_double_clicked)
        self.tag_tabs.currentChanged.connect(self._on_current_changed)
        bar = self.tag_tabs.tabBar()
        bar.setExpanding(False)
        bar.setUsesScrollButtons(True)
        bar.setContextMenuPolicy(Qt.CustomContextMenu)
        bar.customContextMenuRequested.connect(self._tab_context_menu)

        # 控制项做成独立设置组，由主窗口摆到右侧栏，给日志区腾高度
        self.newline_chk = QCheckBox("发送新行")
        self.newline_chk.setChecked(True)
        self.cycle_chk = QCheckBox("循环发送(当前页)")
        self.cycle_chk.toggled.connect(self._toggle_cycle)
        self.period_spin = QSpinBox()
        self.period_spin.setRange(1, 600000)
        self.period_spin.setValue(1000)
        self.period_spin.setSuffix(" ms")

        period_row = QHBoxLayout()
        period_row.addWidget(QLabel("周期:"))
        period_row.addWidget(self.period_spin, 1)
        ctrl = QVBoxLayout()
        ctrl.setContentsMargins(5, 8, 5, 6)
        ctrl.setSpacing(4)
        ctrl.addWidget(self.newline_chk)
        ctrl.addWidget(self.cycle_chk)
        ctrl.addLayout(period_row)
        self.controls_box = QGroupBox("多条发送")
        self.controls_box.setLayout(ctrl)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 2)
        layout.setSpacing(3)
        layout.addWidget(self.tag_tabs)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._cycle_tick)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(300)
        self._save_timer.timeout.connect(self.save)

        self._loading = True
        self._load()
        self._loading = False

    # ---------- 标签管理 ----------

    def _plus_index(self) -> int:
        return self.tag_tabs.count() - 1

    def _is_plus(self, idx: int) -> bool:
        return idx == self._plus_index()

    def _on_tab_clicked(self, idx: int):
        if self._is_plus(idx):
            self.add_tag()

    def _on_tab_double_clicked(self, idx: int):
        if idx >= 0 and not self._is_plus(idx):
            self.rename_tag(idx)

    def _on_current_changed(self, idx: int):
        # "+" 页签不可停留，弹回原页；原页已删除则弹回最后一个真实标签
        if self._is_plus(idx) and self.tag_tabs.count() > 1:
            target = self._prev_index
            if not 0 <= target < self._plus_index():
                target = self._plus_index() - 1
            self.tag_tabs.setCurrentIndex(target)
            return
        self._prev_index = idx
        self.stop_cycle()

    def _tab_context_menu(self, pos):
        bar = self.tag_tabs.tabBar()
        idx = bar.tabAt(pos)
        if idx < 0 or self._is_plus(idx):
            return
        menu = QMenu(self)
        rename_act = menu.addAction("重命名")
        delete_act = menu.addAction("删除标签")
        act = menu.exec(bar.mapToGlobal(pos))
        if act is rename_act:
            self.rename_tag(idx)
        elif act is delete_act:
            self.delete_tag(idx)

    def _unique_name(self, name: str, skip_idx: int = -1) -> bool:
        if name == "+":
            QMessageBox.warning(self, "提示", '标签名不能为 "+"')
            return False
        for i in range(self._plus_index()):
            if i != skip_idx and self.tag_tabs.tabText(i) == name:
                QMessageBox.warning(self, "提示", f"标签 {name} 已存在")
                return False
        return True

    def add_tag(self, name: str | None = None):
        if not name:
            name, ok = QInputDialog.getText(self, "添加标签", "标签名称:")
            if not ok or not name.strip():
                return
            name = name.strip()
        if not self._unique_name(name):
            return
        page = TagPage(self._send_entry, self.schedule_save, name)
        idx = self.tag_tabs.insertTab(self._plus_index(), page, name)
        self.tag_tabs.setCurrentIndex(idx)
        self.save()

    def rename_tag(self, idx: int):
        old = self.tag_tabs.tabText(idx)
        name, ok = QInputDialog.getText(self, "重命名标签", "标签名称:", text=old)
        if not ok or not name.strip() or name.strip() == old:
            return
        name = name.strip()
        if not self._unique_name(name, skip_idx=idx):
            return
        self.tag_tabs.setTabText(idx, name)
        page = self.tag_tabs.widget(idx)
        if isinstance(page, TagPage):
            page.tag_name = name
        self.save()

    def delete_tag(self, idx: int):
        if self.tag_tabs.count() <= 2:  # 一个标签 + "+"
            QMessageBox.warning(self, "提示", "至少保留一个标签")
            return
        name = self.tag_tabs.tabText(idx)
        if QMessageBox.question(self, "删除标签",
                                f"确认删除标签 {name} 及其全部命令？") != \
                QMessageBox.Yes:
            return
        self.tag_tabs.removeTab(idx)
        self.save()

    def _current_page(self) -> TagPage | None:
        w = self.tag_tabs.currentWidget()
        return w if isinstance(w, TagPage) else None

    # ---------- 持久化 ----------

    def _load(self):
        data = {}
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        if not isinstance(data, dict) or not data:
            data = {"默认": []}
        for name, items in data.items():
            page = TagPage(self._send_entry, self.schedule_save, name)
            if items and isinstance(items, list) and isinstance(items[0], dict):
                # 旧格式：扁平条目列表 -> 按每页 10 条切分
                items = [items[i:i + ENTRIES_PER_PAGE]
                         for i in range(0, len(items), ENTRIES_PER_PAGE)]
            page.load_data(items)
            self.tag_tabs.addTab(page, name)
        self.tag_tabs.addTab(QWidget(), "+")  # 固定在末尾的添加入口
        self.tag_tabs.setCurrentIndex(0)

    def schedule_save(self, *_):
        """编辑停止 300ms 后保存，输入过程中也不会因异常退出而丢失。"""
        if not self._loading:
            self._save_timer.start()

    def save(self):
        if self._loading:
            return
        data = {self.tag_tabs.tabText(i): self.tag_tabs.widget(i).to_data()
                for i in range(self._plus_index())}
        temp_path = CONFIG_PATH.with_suffix(".json.tmp")
        try:
            temp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=1),
                encoding="utf-8")
            temp_path.replace(CONFIG_PATH)
        except OSError:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    # ---------- 发送 ----------

    def _send_entry(self, idx) -> bool:
        page = self._current_page()
        if page is None:
            return False
        hex_chk, edit = page.entries[idx]
        text = edit.text()
        if not text:
            return False
        return self._send_func(text, hex_chk.isChecked(),
                               self.newline_chk.isChecked())

    def _toggle_cycle(self, on: bool):
        if on:
            self._cycle_index = 0
            self._timer.start(self.period_spin.value())
        else:
            self._timer.stop()

    def _cycle_tick(self):
        # 重入保护：发送失败弹出的模态对话框会继续跑事件循环，
        # 期间定时器再触发会导致对话框无限叠加
        if self._tick_busy:
            return
        self._tick_busy = True
        try:
            self._timer.setInterval(self.period_spin.value())
            page = self._current_page()
            if page is None:
                self.cycle_chk.setChecked(False)
                return
            # 从当前位置往后找第一条非空条目发送
            for _ in range(ENTRIES_PER_PAGE):
                idx = self._cycle_index
                self._cycle_index = (self._cycle_index + 1) % ENTRIES_PER_PAGE
                if page.entries[idx][1].text():
                    if not self._send_entry(idx):
                        self.cycle_chk.setChecked(False)
                    return
            self.cycle_chk.setChecked(False)  # 全空则停止
        finally:
            self._tick_busy = False

    def stop_cycle(self):
        self.cycle_chk.setChecked(False)


class EntryEditorDialog(QDialog):
    """按标签和页码批量编辑命令，支持中文 INI 格式导入/导出。"""

    HEADERS = ["页码", "序号", "选择", "指令", "描述"]

    def __init__(self, tag_name, items, parent=None):
        super().__init__(parent)
        self.tag_name = tag_name or "默认"
        self.setWindowTitle(f"编辑条目 - {self.tag_name}")
        self.resize(760, 520)

        tag_label = QLabel(f"标签：{self.tag_name}")
        tag_label.setObjectName("editorTitle")
        self.page_summary = QLabel()

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        self._fill(items)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear)
        add_row_btn = QPushButton("添加行")
        add_row_btn.clicked.connect(self._add_row)
        del_row_btn = QPushButton("删除行")
        del_row_btn.clicked.connect(self._del_rows)
        import_btn = QPushButton("导入条目")
        import_btn.clicked.connect(self._import)
        export_btn = QPushButton("导出条目")
        export_btn.clicked.connect(self._export)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("确定")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addWidget(clear_btn)
        btn_row.addWidget(add_row_btn)
        btn_row.addWidget(del_row_btn)
        btn_row.addWidget(import_btn)
        btn_row.addWidget(export_btn)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)

        layout = QVBoxLayout(self)
        title_row = QHBoxLayout()
        title_row.addWidget(tag_label)
        title_row.addStretch()
        title_row.addWidget(self.page_summary)
        layout.addLayout(title_row)
        layout.addWidget(self.table)
        layout.addLayout(btn_row)

    # ---------- 表格读写 ----------

    def _fill(self, items):
        self.table.setRowCount(len(items))
        for r, it in enumerate(items):
            page_item = QTableWidgetItem(str(r // ENTRIES_PER_PAGE + 1))
            page_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            page_item.setTextAlignment(Qt.AlignCenter)
            number_item = QTableWidgetItem(str(r))
            number_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            number_item.setTextAlignment(Qt.AlignCenter)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled |
                         Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if it.get("hex") else Qt.Unchecked)
            chk.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 0, page_item)
            self.table.setItem(r, 1, number_item)
            self.table.setItem(r, 2, chk)
            self.table.setItem(r, 3, QTableWidgetItem(str(it.get("text", ""))))
            self.table.setItem(r, 4, QTableWidgetItem(str(it.get("desc", ""))))
        pages = max(1, (len(items) + ENTRIES_PER_PAGE - 1) // ENTRIES_PER_PAGE)
        self.page_summary.setText(
            f"共 {pages} 页，每页 {ENTRIES_PER_PAGE} 条")

    def result_items(self):
        items = []
        for r in range(self.table.rowCount()):
            chk = self.table.item(r, 2)
            text = self.table.item(r, 3)
            desc = self.table.item(r, 4)
            items.append({
                "hex": chk is not None and chk.checkState() == Qt.Checked,
                "text": text.text() if text else "",
                "desc": desc.text() if desc else "",
            })
        return items

    def _clear(self):
        if QMessageBox.question(self, "清空", "确认清空全部条目？") \
                != QMessageBox.Yes:
            return
        n = max(self.table.rowCount(), ENTRIES_PER_PAGE)
        self._fill([_empty_item() for _ in range(n)])

    def _add_row(self):
        items = self.result_items()
        items.append(_empty_item())
        self._fill(items)
        self.table.scrollToBottom()

    def _del_rows(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                      reverse=True)
        if not rows:
            QMessageBox.warning(self, "提示", "请先选中要删除的行")
            return
        items = self.result_items()
        for r in rows:
            del items[r]
        self._fill(items or [_empty_item()])

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入条目", "", "INI 文件 (*.ini);;所有文件 (*)")
        if not path:
            return
        # interpolation=None：命令里的 % 不被当作插值符
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str  # 保留键名大小写
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                parser.read_file(f)
        except (OSError, configparser.Error) as e:
            QMessageBox.critical(self, "导入失败", str(e))
            return
        # 同时兼容新格式 [指令N] 和旧格式 [itemN]，按编号排序读取。
        def _order(name):
            digits = "".join(c for c in name if c.isdigit())
            return int(digits) if digits else 0
        items = []
        for sec in sorted(parser.sections(), key=_order):
            s = parser[sec]
            if not any(key in s for key in ("选择", "指令", "描述",
                                             "hex", "text", "desc")):
                continue
            # 手动解析选择值：getboolean 遇到非法值会抛异常。
            hexv = s.get("选择", s.get("hex", "False")).strip().lower()
            items.append({
                "hex": hexv in ("1", "true", "yes", "on", "是", "√"),
                "text": s.get("指令", s.get("text", "")),
                "desc": s.get("描述", s.get("desc", "")),
            })
        if items:
            self._fill(items)

    def _export(self):
        safe_label = "".join(
            "_" if c in '<>:"/\\|?*' else c for c in self.tag_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "导出条目", f"xcom_{safe_label}.ini", "INI 文件 (*.ini)")
        if not path:
            return
        if not path.lower().endswith(".ini"):
            path += ".ini"
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        for i, it in enumerate(self.result_items()):
            sec = f"指令{i}"
            parser[sec] = {
                "选择": "True" if it["hex"] else "False",
                "指令": it["text"],
                "描述": it["desc"],
            }
        try:
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write(f"; 标签={self.tag_name}\n")
                f.write(f"; 每页指令数={ENTRIES_PER_PAGE}\n\n")
                parser.write(f, space_around_delimiters=False)
        except OSError as e:
            QMessageBox.critical(self, "导出失败", str(e))
