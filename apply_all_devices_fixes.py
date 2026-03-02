#!/usr/bin/env python3
"""Apply ALL Devices tab fixes at once - complete refactoring"""

with open('ui_application.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("📝 Applying all Devices tab fixes...")

# 1. Add scan_status_var and scan_in_progress flag after _devices_last_scan
for i, line in enumerate(lines):
    if '_devices_last_scan = []' in line and i < 100:
        lines.insert(i+1, '            self.devices_scan_status_var = tk.StringVar(value="Ready")\n')
        lines.insert(i+2, '            self._devices_scan_in_progress = False  # Prevent concurrent scans\n')
        print("✓ Added status var and thread leak protection")
        break

# 2. Replace entire _build_ui_devices section
for i, line in enumerate(lines):
    if 'def _build_ui_devices(self, parent: tk.Frame) -> None:' in line:
        # Find the end of this method (next def or next method at same indentation)
        start_idx = i
        end_idx = i + 1
        for j in range(i + 1, len(lines)):
            if lines[j].startswith('        def _build_ui_'):
                end_idx = j
                break
        
        # Build new method
        new_method = [
            '        def _build_ui_devices(self, parent: tk.Frame) -> None:\n',
            '            header = tk.Frame(parent, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)\n',
            '            header.pack(fill=tk.X, padx=16, pady=(16, 10))\n',
            '    \n',
            '            left = tk.Frame(header, bg=self.colors["panel"])\n',
            '            left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=12, pady=12)\n',
            '            tk.Label(left, text="Devices & Advertising", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 14, "bold")).pack(anchor="w")\n',
            '            tk.Label(left, text="Auto-scan every 3s (5s timeout)", bg=self.colors["panel"], fg=self.colors["muted"]).pack(anchor="w", pady=(2, 0))\n',
            '    \n',
            '            status_frame = tk.Frame(header, bg=self.colors["panel"])\n',
            '            status_frame.pack(side=tk.RIGHT, padx=12, pady=12)\n',
            '            tk.Label(status_frame, textvariable=self.devices_scan_status_var, bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 10, "bold")).pack()\n',
            '    \n',
            '            # Filters row\n',
            '            filters = tk.Frame(parent, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)\n',
            '            filters.pack(fill=tk.X, padx=16, pady=(0, 10))\n',
            '            filters_in = tk.Frame(filters, bg=self.colors["panel"])\n',
            '            filters_in.pack(fill=tk.X, padx=12, pady=8)\n',
            '    \n',
            '            tk.Label(filters_in, text="\\U0001F50D Filters:", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 10))\n',
            '    \n',
            '            tk.Label(filters_in, text="Address:", bg=self.colors["panel"], fg=self.colors["muted"]).pack(side=tk.LEFT, padx=(0, 4))\n',
            '            ttk.Entry(filters_in, textvariable=self.address_prefix_var, width=15).pack(side=tk.LEFT, padx=(0, 12))\n',
            '    \n',
            '            tk.Label(filters_in, text="Name:", bg=self.colors["panel"], fg=self.colors["muted"]).pack(side=tk.LEFT, padx=(0, 4))\n',
            '            ttk.Entry(filters_in, textvariable=self.adv_name_contains_var, width=15).pack(side=tk.LEFT, padx=(0, 12))\n',
            '    \n',
            '            tk.Label(filters_in, text="Service UUID:", bg=self.colors["panel"], fg=self.colors["muted"]).pack(side=tk.LEFT, padx=(0, 4))\n',
            '            ttk.Entry(filters_in, textvariable=self.adv_service_uuid_contains_var, width=12).pack(side=tk.LEFT)\n',
            '    \n',
            '            body = tk.Frame(parent, bg=self.colors["bg"])\n',
            '            body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))\n',
            '    \n',
            '            # Left: Devices list with its own header\n',
            '            left_panel = tk.Frame(body, bg=self.colors["bg"])\n',
            '            left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))\n',
            '    \n',
            '            list_header = tk.Frame(left_panel, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)\n',
            '            list_header.pack(fill=tk.X, pady=(0, 6))\n',
            '            tk.Label(list_header, text="\\U0001F4E1 BLE Devices", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 10, "bold")).pack(padx=10, pady=6, anchor="w")\n',
            '    \n',
            '            cols = ("address", "name", "rssi", "matched")\n',
            '            tree = ttk.Treeview(left_panel, columns=cols, show="headings", height=14)\n',
            '            tree.heading("address", text="Address")\n',
            '            tree.heading("name", text="Name")\n',
            '            tree.heading("rssi", text="RSSI")\n',
            '            tree.heading("matched", text="Match")\n',
            '            tree.column("address", width=180, anchor="w")\n',
            '            tree.column("name", width=220, anchor="w")\n',
            '            tree.column("rssi", width=80, anchor="e")\n',
            '            tree.column("matched", width=80, anchor="center")\n',
            '            tree.pack(fill=tk.BOTH, expand=True)\n',
            '    \n',
            '            tree.bind("<<TreeviewSelect>>", self._devices_on_select)\n',
            '            self.devices_tree = tree\n',
            '    \n',
            '            # Right: Advertising details with its own header\n',
            '            right_panel = tk.Frame(body, bg=self.colors["bg"])\n',
            '            right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(6, 0))\n',
            '    \n',
            '            detail_header = tk.Frame(right_panel, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)\n',
            '            detail_header.pack(fill=tk.X, pady=(0, 6))\n',
            '            tk.Label(detail_header, text="\\U0001F4CB Advertising Details", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 10, "bold")).pack(padx=10, pady=6, anchor="w")\n',
            '    \n',
            '            detail = tk.Frame(right_panel, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)\n',
            '            detail.pack(fill=tk.BOTH, expand=True)\n',
            '    \n',
            '            detail_in = tk.Frame(detail, bg=self.colors["panel"])\n',
            '            detail_in.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)\n',
            '            self.devices_detail = tk.Text(detail_in, wrap="none", bg=self.colors["panel"], fg=self.colors["text"], relief=tk.FLAT)\n',
            '            self.devices_detail.pack(fill=tk.BOTH, expand=True)\n',
            '            self.devices_detail.insert("1.0", "Waiting for scan...\\nDevices will appear automatically.\\nSelect a device to see details.")\n',
            '            self.devices_detail.configure(state=tk.DISABLED)\n',
            '    \n',
            '            self._devices_last_scan = []  # list of (device, adv)\n',
            '    \n',
        ]
        
        # Replace old method with new
        lines[start_idx:end_idx] = new_method
        print("✓ Replaced _build_ui_devices with new layout")
        break

# 3. Fix _devices_scan method
for i, line in enumerate(lines):
    if 'def _devices_scan(self) -> None:' in line:
        # Find method end
        start_idx = i
        end_idx = i + 1
        for j in range(i + 1, len(lines)):
            if lines[j].startswith('        def ') or (lines[j].strip() and not lines[j].startswith('            ') and not lines[j].startswith('        #')):
                end_idx = j
                break
        
        new_scan_method = [
            '        def _devices_scan(self) -> None:\n',
            '            """Trigger one scan pass and merge results into the Devices table (no clear, no dup)."""\n',
            '            # Prevent concurrent scans (fix thread leak)\n',
            '            if self._devices_scan_in_progress:\n',
            '                return\n',
            '            \n',
            '            self._devices_scan_in_progress = True\n',
            '            \n',
            '            try:\n',
            '                self.devices_scan_status_var.set("\\U0001F50D Scanning...")\n',
            '                self.root.update_idletasks()\n',
            '            except Exception:\n',
            '                pass\n',
            '    \n',
            '            # Read current filters (use fixed 5s timeout)\n',
            '            addr_prefix, _mtu, _scan_timeout, _rx_timeout, _rec, _sess, name_contains, svc_contains, mfg_id_hex, mfg_data_hex = self._read_runtime_params()\n',
            '            timeout_s = 5.0  # Fixed 5 second timeout\n',
            '    \n',
            '            def worker():\n',
            '                try:\n',
            '                    async def _do():\n',
            '                        from bleak import BleakScanner\n',
            '                        res = await BleakScanner.discover(timeout=timeout_s, return_adv=True)\n',
            '                        pairs = []\n',
            '                        if isinstance(res, dict):\n',
            '                            for _addr, val in res.items():\n',
            '                                if isinstance(val, tuple) and len(val) == 2:\n',
            '                                    pairs.append(val)\n',
            '                                else:\n',
            '                                    pairs.append((val, None))\n',
            '                        elif isinstance(res, list):\n',
            '                            for item in res:\n',
            '                                if isinstance(item, tuple) and len(item) == 2:\n',
            '                                    pairs.append(item)\n',
            '                                else:\n',
            '                                    pairs.append((item, None))\n',
            '                        return pairs\n',
            '    \n',
            '                    pairs = asyncio.run(_do())\n',
            '                    self.root.after(0, lambda: self._devices_populate(pairs))\n',
            '                except Exception as exc:\n',
            '                    self.root.after(0, lambda: self.devices_scan_status_var.set(f"\\u274c Error: {type(exc).__name__}"))\n',
            '                finally:\n',
            '                    self.root.after(0, lambda: setattr(self, \'_devices_scan_in_progress\', False))\n',
            '    \n',
            '            threading.Thread(target=worker, daemon=True).start()\n',
            '    \n',
        ]
        
        lines[start_idx:end_idx] = new_scan_method
        print("✓ Fixed _devices_scan (thread leak + 5s timeout)")
        break

# 4. Fix _devices_populate to update status instead of details
for i, line in enumerate(lines):
    if 'def _devices_populate(self, pairs):' in line:
        # Find the stats line
        for j in range(i, min(i + 120, len(lines))):
            if 'self._devices_set_details(f"Known devices:' in lines[j]:
                lines[j:j+1] = [
                    '            # Update status with results\n',
                    '            total = len(self._devices_by_addr)\n',
                    '            if added > 0:\n',
                    '                self.devices_scan_status_var.set(f"\\u2713 {total} devices (+{added} new, {matched} matched)")\n',
                    '            else:\n',
                    '                self.devices_scan_status_var.set(f"\\u2713 {total} devices ({matched} matched)")\n',
                ]
                print("✓ Fixed _devices_populate (stats in status)")
                break
        break

# 5. Fix _devices_on_select to not overwrite details
for i, line in enumerate(lines):
    if 'def _devices_on_select(self, _evt):' in line:
        for j in range(i, min(i + 20, len(lines))):
            if 'self._devices_set_details(txt)' in lines[j]:
                lines[j:j+1] = [
                    '            # Display device details directly\n',
                    '            self.devices_detail.configure(state=tk.NORMAL)\n',
                    '            self.devices_detail.delete("1.0", tk.END)\n',
                    '            self.devices_detail.insert("1.0", txt)\n',
                    '            self.devices_detail.configure(state=tk.DISABLED)\n',
                ]
                print("✓ Fixed _devices_on_select")
                break
        break

with open('ui_application.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("\n✅ ALL FIXES APPLIED!")
print("   • Thread leak fixed")
print("   • Timeout: 5 seconds")
print("   • Stats in status bar")
print("   • Filters visible")
print("   • UI separated visually")
