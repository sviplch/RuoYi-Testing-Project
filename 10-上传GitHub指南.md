# 10 — 上传 GitHub 指南

> 记录本项目怎么传到 GitHub，以及以后怎么更新。自己维护用，不用背。

---

## 一、仓库信息

| 项目 | 内容 |
|------|------|
| 仓库地址 | https://github.com/sviplch/RuoYi-Testing-Project |
| 可见性 | Public（公开） |
| 默认分支 | main |
| 本地目录 | `C:\Users\20348\Desktop\work\软件测试实战项目` |

---

## 二、以后更新文档（改完再传一次）

以后你改了文档（比如把测试报告里的【执行后填】换成真实数字），只需在**该目录下**开终端跑这三条：

```bash
git add -A
git commit -m "更新测试报告执行结果"
git push
```

- `git add -A`：把所有改动加入暂存
- `git commit -m "..."`：提交，引号里写这次改了什么
- `git push`：推送到 GitHub（已经登录过，不会再弹窗）

---

## 三、新建另一个项目仓库的完整步骤

以后换新项目，重复下面这套：

```bash
# 1. 进入项目目录，初始化仓库
cd 你的项目目录
git init -b main

# 2. 配置身份（第一次配一次即可）
git config user.name "sviplch"
git config user.email "2034839897@qq.com"

# 3. 提交
git add -A
git commit -m "初始化项目"

# 4. 去 github.com 建一个空仓库（不要勾 README/.gitignore/license）
#    记下仓库名，然后绑定并推送：
git remote add origin https://github.com/sviplch/仓库名.git
git push -u origin main
```

> 第一次 push 会弹浏览器让你授权，点 Authorize 即可，之后永久记住。

---

## 四、常见问题

| 现象 | 原因 | 解决 |
|------|------|------|
| `warning: LF will be replaced by CRLF` | Windows 换行符差异，无害 | 不用管 |
| `remote origin already exists` | 已经绑过 remote | `git remote set-url origin 新地址` |
| push 提示登录 | 第一次推送 | 浏览器弹窗授权一次即可 |
| `fatal: not a git repository` | 终端不在项目目录 | 先 `cd` 到项目目录 |

---

## 五、几个要点记住

1. **不用 gh CLI 也能推**：Windows 的 Git 凭据管理器会在第一次 push 时自动弹浏览器登录，之后记住。所以普通更新只需要 `git push`。
2. **空仓库别勾 README**：本地已经有 README 时，网页建仓别勾「Add a README」，否则 push 会冲突。
3. **公开仓库里的邮箱是可见的**：commit 里带了 `2034839897@qq.com`，别人能看到。如果不希望公开邮箱，可以到 GitHub 设置里改用 `xxx@users.noreply.github.com` 匿名邮箱。
