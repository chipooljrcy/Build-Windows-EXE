import os
import sys
import hashlib
import threading
import time
import string
import subprocess
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

class FileMasterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("全能文件管家 - 重复清理 & 极速搜索 (类Everything)")
        self.root.geometry("1050x680")
        self.root.minsize(900, 600)

        # 状态控制变量
        self.is_scanning = False
        self.stop_scan_flag = False
        self.duplicate_groups = {}  # { (size, md5): [file_info_dict, ...] }
        self.checked_items = set()  # Treeview item IDs that are checked

        # Everything 搜索索引缓存
        self.file_index = []  # [(filename_lower, filename, full_path, size_str, mtime_str), ...]
        self.is_indexing = False

        self._setup_styles()
        self._build_ui()

    def _setup_styles(self):
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Treeview", rowheight=26, font=("Microsoft YaHei", 9))
        style.configure("Treeview.Heading", font=("Microsoft YaHei", 9, "bold"))
        style.configure("TButton", font=("Microsoft YaHei", 9))
        style.configure("TLabel", font=("Microsoft YaHei", 9))

    def _build_ui(self):
        # 顶部选项卡
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Tab 1: 重复文件扫描与清理
        self.tab_dup = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_dup, text=" 🔍 重复文件清理 (软件/安装包/大文件) ")
        self._build_dup_tab()

        # Tab 2: 极速文件搜索 (类 Everything)
        self.tab_search = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_search, text=" ⚡ 极速文件名搜索 (类 Everything) ")
        self._build_search_tab()

    # =========================================================================
    # Tab 1: 重复文件扫描 UI 与逻辑
    # =========================================================================
    def _build_dup_tab(self):
        # 1. 顶部控制栏
        ctrl_frame = ttk.LabelFrame(self.tab_dup, text="扫描设置", padding=10)
        ctrl_frame.pack(fill=tk.X, padx=8, pady=5)

        # 模式选择
        self.scan_mode_var = tk.StringVar(value="folder")
        rb_folder = ttk.Radiobutton(ctrl_frame, text="指定文件夹扫描", variable=self.scan_mode_var, value="folder", command=self._toggle_scan_mode)
        rb_folder.grid(row=0, column=0, padx=5, sticky=tk.W)

        self.folder_path_var = tk.StringVar(value=os.path.expanduser("~\\Downloads"))
        self.entry_folder = ttk.Entry(ctrl_frame, textvariable=self.folder_path_var, width=42)
        self.entry_folder.grid(row=0, column=1, padx=5)

        self.btn_browse = ttk.Button(ctrl_frame, text="浏览...", command=self._browse_folder, width=8)
        self.btn_browse.grid(row=0, column=2, padx=5)

        rb_full = ttk.Radiobutton(ctrl_frame, text="全盘扫描 (所有本地磁盘)", variable=self.scan_mode_var, value="full", command=self._toggle_scan_mode)
        rb_full.grid(row=0, column=3, padx=15, sticky=tk.W)

        # 过滤类型
        ttk.Label(ctrl_frame, text="文件类型过滤:").grid(row=1, column=0, padx=5, pady=8, sticky=tk.W)
        self.filter_var = tk.StringVar(value="all")
        filter_frame = ttk.Frame(ctrl_frame)
        filter_frame.grid(row=1, column=1, columnspan=3, sticky=tk.W)
        ttk.Radiobutton(filter_frame, text="所有文件", variable=self.filter_var, value="all").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(filter_frame, text="仅软件/安装包 (.exe/.msi/.dmg/.zip/.rar/.7z)", variable=self.filter_var, value="software").pack(side=tk.LEFT, padx=10)
        
        ttk.Label(filter_frame, text="最小体积(MB):").pack(side=tk.LEFT, padx=(15, 2))
        self.min_size_var = tk.StringVar(value="1")
        ttk.Entry(filter_frame, textvariable=self.min_size_var, width=6).pack(side=tk.LEFT)

        # 扫描按钮
        btn_box = ttk.Frame(ctrl_frame)
        btn_box.grid(row=0, column=4, rowspan=2, padx=10, sticky=tk.E)
        self.btn_start_scan = ttk.Button(btn_box, text="🚀 开始扫描", command=self.start_dup_scan, width=14)
        self.btn_start_scan.pack(pady=2)
        self.btn_stop_scan = ttk.Button(btn_box, text="🛑 停止扫描", command=self.stop_dup_scan, state=tk.DISABLED, width=14)
        self.btn_stop_scan.pack(pady=2)

        # 2. 智能操作栏
        action_frame = ttk.Frame(self.tab_dup, padding=(8, 4))
        action_frame.pack(fill=tk.X)

        ttk.Button(action_frame, text="✨ 智能勾选重复文件 (推荐)", command=self.smart_select_duplicates).pack(side=tk.LEFT, padx=4)
        ttk.Button(action_frame, text="取消全选", command=self.clear_all_selections).pack(side=tk.LEFT, padx=4)
        ttk.Label(action_frame, text="💡 提示：双击列表项可切换勾选状态；右键可打开所在文件夹", foreground="#555555").pack(side=tk.LEFT, padx=15)

        self.btn_delete = ttk.Button(action_frame, text="🗑️ 删除勾选的文件", command=self.delete_selected_files)
        self.btn_delete.pack(side=tk.RIGHT, padx=4)

        # 3. 结果列表 Treeview
        tree_frame = ttk.Frame(self.tab_dup)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        columns = ("check", "name", "folder", "size", "mtime", "md5")
        self.dup_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        self.dup_tree.heading("check", text="状态")
        self.dup_tree.heading("name", text="文件名")
        self.dup_tree.heading("folder", text="所在目录")
        self.dup_tree.heading("size", text="大小")
        self.dup_tree.heading("mtime", text="修改时间")
        self.dup_tree.heading("md5", text="MD5 校验值")

        self.dup_tree.column("check", width=65, anchor=tk.CENTER, stretch=False)
        self.dup_tree.column("name", width=220, anchor=tk.W)
        self.dup_tree.column("folder", width=360, anchor=tk.W)
        self.dup_tree.column("size", width=95, anchor=tk.E, stretch=False)
        self.dup_tree.column("mtime", width=135, anchor=tk.CENTER, stretch=False)
        self.dup_tree.column("md5", width=120, anchor=tk.CENTER, stretch=False)

        # 颜色标签
        self.dup_tree.tag_configure("group_header", background="#E8F0FE", font=("Microsoft YaHei", 9, "bold"))
        self.dup_tree.tag_configure("checked_row", background="#FFEFEF", foreground="#C00000")
        self.dup_tree.tag_configure("keep_row", background="#FFFFFF", foreground="#202020")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.dup_tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.dup_tree.xview)
        self.dup_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.dup_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # 绑定事件
        self.dup_tree.bind("<Double-1>", self._on_dup_tree_double_click)
        self.dup_tree.bind("<Button-3>", self._on_dup_tree_right_click)

        # 4. 底部状态栏
        self.dup_status_var = tk.StringVar(value="就绪：请选择扫描模式并点击“开始扫描”")
        status_bar = ttk.Label(self.tab_dup, textvariable=self.dup_status_var, relief=tk.SUNKEN, anchor=tk.W, padding=4)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _toggle_scan_mode(self):
        if self.scan_mode_var.get() == "full":
            self.entry_folder.configure(state=tk.DISABLED)
            self.btn_browse.configure(state=tk.DISABLED)
        else:
            self.entry_folder.configure(state=tk.NORMAL)
            self.btn_browse.configure(state=tk.NORMAL)

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="选择要扫描的文件夹")
        if folder:
            self.folder_path_var.set(folder)

    def _get_target_roots(self):
        if self.scan_mode_var.get() == "folder":
            path = self.folder_path_var.get().strip()
            if not os.path.isdir(path):
                messagebox.showwarning("路径无效", "所选文件夹不存在，请重新选择！")
                return []
            return [path]
        else:
            # 获取全盘盘符
            if os.name == "nt":
                drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
                return drives
            else:
                return ["/"]

    def start_dup_scan(self):
        roots = self._get_target_roots()
        if not roots:
            return

        try:
            min_mb = float(self.min_size_var.get().strip() or 0)
        except ValueError:
            min_mb = 0
        min_bytes = int(min_mb * 1024 * 1024)

        # 清空旧数据
        for item in self.dup_tree.get_children():
            self.dup_tree.delete(item)
        self.duplicate_groups.clear()
        self.checked_items.clear()

        self.is_scanning = True
        self.stop_scan_flag = False
        self.btn_start_scan.configure(state=tk.DISABLED)
        self.btn_stop_scan.configure(state=tk.NORMAL)

        threading.Thread(
            target=self._scan_duplicates_worker,
            args=(roots, self.filter_var.get(), min_bytes),
            daemon=True
        ).start()

    def stop_dup_scan(self):
        if self.is_scanning:
            self.stop_scan_flag = True
            self.dup_status_var.set("正在停止扫描，请稍候...")

    def _scan_duplicates_worker(self, roots, filter_mode, min_bytes):
        start_time = time.time()
        size_map = {}  # { size: [filepath, ...] }
        skip_dirs = {"$RECYCLE.BIN", "System Volume Information", "Windows", "ProgramData", ".git", "node_modules", "AppData"}
        software_exts = {".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".zip", ".rar", ".7z", ".iso", ".apk"}

        scanned_count = 0
        for root_dir in roots:
            for dirpath, dirnames, filenames in os.walk(root_dir):
                if self.stop_scan_flag:
                    break
                # 过滤系统目录防止卡死或误删系统文件
                dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith("$")]

                for fname in filenames:
                    if self.stop_scan_flag:
                        break
                    ext = os.path.splitext(fname)[1].lower()
                    if filter_mode == "software" and ext not in software_exts:
                        continue

                    full_path = os.path.join(dirpath, fname)
                    try:
                        st = os.stat(full_path)
                        fsize = st.st_size
                        if fsize < min_bytes or fsize == 0:
                            continue
                        size_map.setdefault(fsize, []).append((full_path, st.st_mtime))
                        scanned_count += 1
                        if scanned_count % 300 == 0:
                            self.root.after(0, self.dup_status_var.set, f"正在扫描文件... 已检索 {scanned_count} 个符合条件的文件 ({dirpath[:50]}...)")
                    except (PermissionError, FileNotFoundError, OSError):
                        continue

        # 筛选出大小相同的文件组
        potential_groups = {sz: paths for sz, paths in size_map.items() if len(paths) > 1}
        total_candidates = sum(len(v) for v in potential_groups.values())

        # 第二阶段：先算头部快速 Hash，再算完整 MD5
        dup_groups = {}
        processed = 0

        for fsize, file_list in potential_groups.items():
            if self.stop_scan_flag:
                break
            # 先对前 64KB 做快速哈希分组
            quick_map = {}
            for fpath, mtime in file_list:
                if self.stop_scan_flag:
                    break
                processed += 1
                if processed % 20 == 0:
                    self.root.after(0, self.dup_status_var.set, f"正在比对内容特征 ({processed}/{total_candidates})...")
                qhash = self._calc_hash(fpath, first_chunk_only=True)
                if qhash:
                    quick_map.setdefault(qhash, []).append((fpath, mtime))

            # 对快速哈希一致的文件计算完整 MD5
            for qhash, q_list in quick_map.items():
                if len(q_list) < 2:
                    continue
                full_map = {}
                for fpath, mtime in q_list:
                    if self.stop_scan_flag:
                        break
                    fhash = self._calc_hash(fpath, first_chunk_only=False)
                    if fhash:
                        full_map.setdefault(fhash, []).append({
                            "path": fpath,
                            "name": os.path.basename(fpath),
                            "folder": os.path.dirname(fpath),
                            "size": fsize,
                            "mtime": mtime,
                            "md5": fhash
                        })
                for fhash, final_list in full_map.items():
                    if len(final_list) > 1:
                        dup_groups[(fsize, fhash)] = final_list

        elapsed = time.time() - start_time
        self.root.after(0, self._finish_dup_scan, dup_groups, scanned_count, elapsed)

    def _calc_hash(self, filepath, first_chunk_only=False):
        try:
            hasher = hashlib.md5()
            with open(filepath, "rb") as f:
                if first_chunk_only:
                    chunk = f.read(65536)
                    hasher.update(chunk)
                else:
                    while chunk := f.read(1048576):  # 1MB chunks
                        if self.stop_scan_flag:
                            return None
                        hasher.update(chunk)
            return hasher.hexdigest()
        except (PermissionError, FileNotFoundError, OSError):
            return None

    def _finish_dup_scan(self, dup_groups, scanned_count, elapsed):
        self.is_scanning = False
        self.btn_start_scan.configure(state=tk.NORMAL)
        self.btn_stop_scan.configure(state=tk.DISABLED)
        self.duplicate_groups = dup_groups

        # 按文件从大到小排序展示
        sorted_keys = sorted(dup_groups.keys(), key=lambda x: x[0], reverse=True)
        group_idx = 0
        total_dup_files = 0
        wasted_bytes = 0

        for key in sorted_keys:
            fsize, fhash = key
            items = dup_groups[key]
            group_idx += 1
            total_dup_files += len(items)
            wasted_bytes += fsize * (len(items) - 1)

            # 插入分组标题行
            header_id = f"group_{group_idx}"
            self.dup_tree.insert(
                "", tk.END, iid=header_id,
                values=("📁 分组", f"第 {group_idx} 组 ({len(items)} 个相同文件)", "—", self._format_size(fsize), "—", fhash[:12]),
                tags=("group_header",), open=True
            )

            for idx, info in enumerate(items):
                item_id = f"file_{group_idx}_{idx}"
                mtime_str = datetime.fromtimestamp(info["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
                self.dup_tree.insert(
                    header_id, tk.END, iid=item_id,
                    values=("☐ 保留", info["name"], info["folder"], self._format_size(info["size"]), mtime_str, info["md5"]),
                    tags=("keep_row",)
                )

        # 自动执行一次智能勾选
        if group_idx > 0:
            self.smart_select_duplicates()

        status_msg = (
            f"扫描完成 (耗时 {elapsed:.1f} 秒) | 共扫描 {scanned_count} 个文件 | "
            f"发现 {group_idx} 组重复文件 (共 {total_dup_files} 个)，预计可释放空间：{self._format_size(wasted_bytes)}"
        )
        self.dup_status_var.set(status_msg)

    def smart_select_duplicates(self):
        """
        智能选择算法：
        每组重复文件中必须严格保留 1 个文件，其余勾选为“待删除”。
        优先级评分（分数越低越应该保留，分数越高越优先删除）：
        1. 文件名包含 (1), (2), 副本, copy 等字样的优先删除
        2. 路径长度更深或临时目录的优先删除
        3. 修改时间较新的副本优先删除（保留最早的原始文件）
        """
        self.clear_all_selections()
        import re
        copy_pattern = re.compile(r'(\(\d+\)|副本|copy|[-_]\d+)', re.IGNORECASE)

        selected_count = 0
        free_bytes = 0

        for group_id in self.dup_tree.get_children():
            children = self.dup_tree.get_children(group_id)
            if len(children) < 2:
                continue

            scored_children = []
            for child_id in children:
                vals = self.dup_tree.item(child_id, "values")
                fname = vals[1]
                folder = vals[2]
                mtime_str = vals[4]

                has_copy_tag = 1 if copy_pattern.search(fname) else 0
                scored_children.append((has_copy_tag, len(fname), mtime_str, child_id))

            # 排序：没有副本标记的排第一，文件名短的排第一，时间早的排第一 -> 第一个作为保留项
            scored_children.sort(key=lambda x: (x[0], x[1], x[2]))

            # 保留第一个，勾选其余所有
            for _, _, _, child_id in scored_children[1:]:
                self._set_item_checked(child_id, True)
                selected_count += 1

        self._update_selection_summary()

    def clear_all_selections(self):
        for item_id in list(self.checked_items):
            self._set_item_checked(item_id, False)
        self._update_selection_summary()

    def _set_item_checked(self, item_id, checked: bool):
        vals = list(self.dup_tree.item(item_id, "values"))
        if checked:
            vals[0] = "☑️ 删除"
            self.dup_tree.item(item_id, values=vals, tags=("checked_row",))
            self.checked_items.add(item_id)
        else:
            vals[0] = "☐ 保留"
            self.dup_tree.item(item_id, values=vals, tags=("keep_row",))
            self.checked_items.discard(item_id)

    def _on_dup_tree_double_click(self, event):
        item_id = self.dup_tree.identify_row(event.y)
        if not item_id or item_id.startswith("group_"):
            return
        is_checked = item_id in self.checked_items
        self._set_item_checked(item_id, not is_checked)
        self._update_selection_summary()

    def _on_dup_tree_right_click(self, event):
        item_id = self.dup_tree.identify_row(event.y)
        if not item_id or item_id.startswith("group_"):
            return
        self.dup_tree.selection_set(item_id)
        vals = self.dup_tree.item(item_id, "values")
        full_path = os.path.join(vals[2], vals[1])
        self._open_in_explorer(full_path)

    def _update_selection_summary(self):
        count = len(self.checked_items)
        self.dup_status_var.set(f"当前已智能勾选 {count} 个待清理的重复文件（双击任意行可手动切换保留/删除，右键可定位文件位置）")

    def delete_selected_files(self):
        if not self.checked_items:
            messagebox.showinfo("提示", "请先勾选需要删除的重复文件！")
            return

        # 安全检查：防止用户把某一组全部勾选删除
        for group_id in self.dup_tree.get_children():
            children = self.dup_tree.get_children(group_id)
            if children and all(c in self.checked_items for c in children):
                if not messagebox.askyesno("安全警告", "检测到有分组内的所有文件都被勾选了（未保留原文件）！是否仍要继续删除？"):
                    return
                break

        confirm = messagebox.askyesno(
            "确认删除",
            f"确定要永久删除已勾选的 {len(self.checked_items)} 个重复文件吗？\n（建议先核对列表，被标记为“☐ 保留”的文件不会受影响）"
        )
        if not confirm:
            return

        deleted_count = 0
        errors = []
        for item_id in list(self.checked_items):
            vals = self.dup_tree.item(item_id, "values")
            full_path = os.path.join(vals[2], vals[1])
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
                self.dup_tree.delete(item_id)
                self.checked_items.discard(item_id)
                deleted_count += 1
            except Exception as e:
                errors.append(f"{full_path}: {str(e)}")

        # 清理只剩1个文件的分组
        for group_id in list(self.dup_tree.get_children()):
            if len(self.dup_tree.get_children(group_id)) <= 1:
                self.dup_tree.delete(group_id)

        msg = f"成功清理 {deleted_count} 个重复文件！"
        if errors:
            msg += f"\n有 {len(errors)} 个文件因权限或占用无法删除。"
        messagebox.showinfo("清理完成", msg)
        self._update_selection_summary()

    # =========================================================================
    # Tab 2: 类 Everything 极速文件搜索 UI 与逻辑
    # =========================================================================
    def _build_search_tab(self):
        # 1. 顶部索引与搜索栏
        top_frame = ttk.LabelFrame(self.tab_search, text="极速文件搜索 (支持实时匹配文件名)", padding=10)
        top_frame.pack(fill=tk.X, padx=8, pady=5)

        ttk.Label(top_frame, text="索引范围:").grid(row=0, column=0, padx=5, sticky=tk.W)
        self.search_scope_var = tk.StringVar(value="全盘 (所有磁盘)")
        self.scope_combo = ttk.Combobox(top_frame, textvariable=self.search_scope_var, width=28, state="readonly")
        self._populate_drives_combo()
        self.scope_combo.grid(row=0, column=1, padx=5, sticky=tk.W)

        ttk.Button(top_frame, text="选择特定目录...", command=self._choose_search_dir).grid(row=0, column=2, padx=5)
        self.btn_build_idx = ttk.Button(top_frame, text="🔄 建立/刷新文件索引", command=self.build_search_index)
        self.btn_build_idx.grid(row=0, column=3, padx=10)

        # 搜索输入框
        ttk.Label(top_frame, text="🔍 输入文件名关键字:", font=("Microsoft YaHei", 10, "bold")).grid(row=1, column=0, padx=5, pady=10, sticky=tk.W)
        self.search_query_var = tk.StringVar()
        self.search_query_var.trace_add("write", self._on_search_input_change)
        search_entry = ttk.Entry(top_frame, textvariable=self.search_query_var, width=55, font=("Microsoft YaHei", 10))
        search_entry.grid(row=1, column=1, columnspan=2, padx=5, pady=10, sticky=tk.EW)

        ttk.Label(top_frame, text="(多个词用空格分隔，例如: chrome .exe)", foreground="#666666").grid(row=1, column=3, padx=5, sticky=tk.W)

        # 2. 搜索结果 Treeview
        res_frame = ttk.Frame(self.tab_search)
        res_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        cols = ("name", "path", "size", "mtime")
        self.search_tree = ttk.Treeview(res_frame, columns=cols, show="headings", selectmode="browse")
        self.search_tree.heading("name", text="文件名")
        self.search_tree.heading("path", text="完整路径 (双击直接打开文件 / 右键定位文件夹)")
        self.search_tree.heading("size", text="大小")
        self.search_tree.heading("mtime", text="修改时间")

        self.search_tree.column("name", width=240, anchor=tk.W)
        self.search_tree.column("path", width=500, anchor=tk.W)
        self.search_tree.column("size", width=100, anchor=tk.E, stretch=False)
        self.search_tree.column("mtime", width=140, anchor=tk.CENTER, stretch=False)

        vsb2 = ttk.Scrollbar(res_frame, orient="vertical", command=self.search_tree.yview)
        hsb2 = ttk.Scrollbar(res_frame, orient="horizontal", command=self.search_tree.xview)
        self.search_tree.configure(yscrollcommand=vsb2.set, xscrollcommand=hsb2.set)

        self.search_tree.grid(row=0, column=0, sticky="nsew")
        vsb2.grid(row=0, column=1, sticky="ns")
        hsb2.grid(row=1, column=0, sticky="ew")
        res_frame.grid_rowconfigure(0, weight=1)
        res_frame.grid_columnconfigure(0, weight=1)

        self.search_tree.bind("<Double-1>", self._on_search_double_click)
        self.search_tree.bind("<Button-3>", self._on_search_right_click)

        # 3. 底部状态栏
        self.search_status_var = tk.StringVar(value="提示：首次使用请先点击上方“建立/刷新文件索引”，之后即可享受毫秒级实时文件名搜索！")
        s_bar = ttk.Label(self.tab_search, textvariable=self.search_status_var, relief=tk.SUNKEN, anchor=tk.W, padding=4)
        s_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _populate_drives_combo(self):
        options = ["全盘 (所有磁盘)"]
        if os.name == "nt":
            for d in string.ascii_uppercase:
                drive = f"{d}:\\"
                if os.path.exists(drive):
                    options.append(drive)
        else:
            options.append(os.path.expanduser("~"))
        self.scope_combo["values"] = options

    def _choose_search_dir(self):
        d = filedialog.askdirectory(title="选择要建立搜索索引的文件夹")
        if d:
            vals = list(self.scope_combo["values"])
            if d not in vals:
                vals.append(d)
                self.scope_combo["values"] = vals
            self.search_scope_var.set(d)

    def build_search_index(self):
        if self.is_indexing:
            return
        scope = self.search_scope_var.get()
        if scope == "全盘 (所有磁盘)":
            if os.name == "nt":
                roots = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
            else:
                roots = ["/"]
        else:
            roots = [scope]

        self.is_indexing = True
        self.btn_build_idx.configure(state=tk.DISABLED)
        threading.Thread(target=self._index_worker, args=(roots,), daemon=True).start()

    def _index_worker(self, roots):
        t0 = time.time()
        temp_index = []
        count = 0
        skip_dirs = {"$RECYCLE.BIN", "System Volume Information"}

        for r in roots:
            for dirpath, dirnames, filenames in os.walk(r):
                dirnames[:] = [d for d in dirnames if d not in skip_dirs]
                for fname in filenames:
                    full_p = os.path.join(dirpath, fname)
                    try:
                        st = os.stat(full_p)
                        sz_str = self._format_size(st.st_size)
                        mt_str = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
                    except OSError:
                        sz_str = "-"
                        mt_str = "-"
                    temp_index.append((fname.lower(), fname, full_p, sz_str, mt_str))
                    count += 1
                    if count % 2000 == 0:
                        self.root.after(0, self.search_status_var.set, f"正在高速建立索引... 已收录 {count} 个文件")

        elapsed = time.time() - t0
        self.file_index = temp_index
        self.is_indexing = False
        self.root.after(0, self._finish_indexing, count, elapsed)

    def _finish_indexing(self, count, elapsed):
        self.btn_build_idx.configure(state=tk.NORMAL)
        self.search_status_var.set(f"索引建立完成！共收录 {count} 个文件 (耗时 {elapsed:.1f} 秒)。现在可在上方输入框实时搜索。")
        self._on_search_input_change()

    def _on_search_input_change(self, *args):
        for item in self.search_tree.get_children():
            self.search_tree.delete(item)

        if not self.file_index:
            return

        query = self.search_query_var.get().strip().lower()
        keywords = [k for k in query.split() if k]

        matched = 0
        max_display = 500  # 限制界面最多渲染前 500 条保证如 Everything 般丝滑不卡顿

        for fname_low, fname, full_p, sz_str, mt_str in self.file_index:
            if not keywords or all(k in fname_low for k in keywords):
                self.search_tree.insert("", tk.END, values=(fname, full_p, sz_str, mt_str))
                matched += 1
                if matched >= max_display:
                    break

        if matched >= max_display:
            self.search_status_var.set(f"实时显示前 {max_display} 条匹配结果（请继续输入关键字缩小范围） | 总索引库: {len(self.file_index)} 个文件")
        else:
            self.search_status_var.set(f"找到 {matched} 个匹配文件 | 总索引库: {len(self.file_index)} 个文件")

    def _on_search_double_click(self, event):
        item_id = self.search_tree.identify_row(event.y)
        if not item_id:
            return
        full_path = self.search_tree.item(item_id, "values")[1]
        if os.path.exists(full_path):
            try:
                if os.name == "nt":
                    os.startfile(full_path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", full_path])
                else:
                    subprocess.Popen(["xdg-open", full_path])
            except Exception as e:
                messagebox.showerror("打开失败", str(e))

    def _on_search_right_click(self, event):
        item_id = self.search_tree.identify_row(event.y)
        if not item_id:
            return
        self.search_tree.selection_set(item_id)
        full_path = self.search_tree.item(item_id, "values")[1]
        self._open_in_explorer(full_path)

    # =========================================================================
    # 通用工具函数
    # =========================================================================
    def _open_in_explorer(self, full_path):
        if not os.path.exists(full_path):
            return
        if os.name == "nt":
            subprocess.Popen(f'explorer /select,"{full_path}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", full_path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(full_path)])

    @staticmethod
    def _format_size(size_bytes):
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"


if __name__ == "__main__":
    root = tk.Tk()
    app = FileMasterApp(root)
    root.mainloop()