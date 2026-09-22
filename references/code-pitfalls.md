# execute_code常见错误

## Import错误

**禁止写法：**
```python
from hermes_tools import terminal, re
```
`re`是Python标准库，不能从hermes_tools导入。会报`ImportError: cannot import name 're'`。

**正确写法：**
```python
import re
from hermes_tools import terminal
```

## 变量未定义

在for循环中解析腾讯行情时，确保`continue`在变量赋值之前：

```python
for l in output.split("\n"):
    if '="' not in l: continue
    m = re.search(r'="([^"]*)"', l)
    if not m: continue          # ← 这个continue必须在p赋值前
    p = m.group(1).split("~")   # 到这里p一定存在
    if len(p) < 40: continue
```

**错误写法：**
```python
for l in output.split("\n"):
    m = re.search(r'="([^"]*)"', l)
    if not m: continue
    p = m.group(1).split("~")   # 可能因None而跳过
```

---

## Python解释器路径（2026-08-21，重要纠错）

**结论：本机有 Python，可以直接跑 templates/ 下的脚本。此前"本机无Python"的判断是错的。**

```bash
D:/Anaconda/python.exe          # Python 3.11.5, pandas 2.0.3, requests 2.32.3
```

### 为什么会误判成"没有Python"

PATH 里的 `python` 解析到微软商店的**应用执行别名占位符**：

```
C:\Users\zhang\AppData\Local\Microsoft\WindowsApps\python.exe   ← 版本 0.0.0.0，执行返回 exit 9009
```

`command -v python` / `Get-Command python` **都能找到它**，看起来像装了；但一执行就失败。
**只用 `command -v` 探测会得出错误结论——必须实际跑 `-V` 并检查退出码。**

真实的 conda 安装在 `D:\Anaconda`，不在 Claude Code 继承的 PATH 里。环境清单见 `~/.conda/environments.txt`：

```
D:\Anaconda                    # base（用这个）
D:\Anaconda\envs\hotsearch
D:\Anaconda\envs\douyinlive
```

### 调用姿势（两条都要）

```bash
PYTHONIOENCODING=utf-8 "D:/Anaconda/python.exe" templates/atr-stop.py
```

- **必须写绝对路径**，`python` / `python3` 会打到占位符上；
- **必须带 `PYTHONIOENCODING=utf-8`**，否则控制台按 GBK 输出：中文乱码，且脚本里的 emoji（✅/🚀）会直接抛
  `UnicodeEncodeError: 'gbk' codec can't encode character`，脚本**中途崩掉**而不是只是显示难看。

### 影响

templates/ 下 7 个脚本（atr-stop / closing-check / cost-calc / emotion-temp / lhb-fetch / picks-ledger /
portfolio-ledger）全部通过编译且实测可运行（含腾讯K线联网取数）。
**不要再用 PowerShell 手搓等价计算**——直接跑脚本。
