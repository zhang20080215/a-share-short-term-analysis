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
