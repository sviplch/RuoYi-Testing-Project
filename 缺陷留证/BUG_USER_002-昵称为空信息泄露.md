# BUG_USER_002 — 新增用户昵称为空报 500 并泄露信息

## 基本信息

| 项目 | 内容 |
|------|------|
| Bug 编号 | BUG_USER_002 |
| 标题 | 新增用户昵称为空报 500，泄露 SQL、服务器路径与内部类名 |
| 模块 | 用户管理 |
| 严重程度 | 严重（信息泄露） |
| 状态 | 新建（已复现） |
| 复现日期 | 2026-09-05 |
| 复现环境 | Spring Boot 2.5.15 + MySQL 8.0（ry_vue 库） |

## 复现步骤

1. 以 admin/admin123 登录系统，获取 token
2. 调用新增用户接口，昵称字段传空（`nickName: ""` 或不传该字段）
3. 观察响应

## 请求

```
POST http://localhost:8080/system/user
Authorization: Bearer {token}
Content-Type: application/json

{
  "userName": "test_nick_empty",
  "nickName": "",
  "deptId": 103,
  "password": "12345"
}
```

## 真实响应（实测抓取）

```json
{
  "code": 500,
  "msg": "### Error updating database.  Cause: java.sql.SQLException: Field 'nick_name' doesn't have a default value\n### The error may exist in URL [jar:file:/C:/projects/RuoYi-Vue/ruoyi-admin/target/ruoyi-admin.jar!/BOOT-INF/lib/ruoyi-system-3.9.2.jar!/mapper/system/SysUserMapper.xml]\n### The error may involve com.ruoyi.system.mapper.SysUserMapper.insertUser-Inline\n### The error occurred while setting parameters\n### SQL: insert into sys_user( dept_id, user_name, password, create_by, create_time ) values( ?, ?, ?, ?, sysdate() )\n### Cause: java.sql.SQLException: Field 'nick_name' doesn't have a default value"
}
```

## 泄露的三层信息

| 泄露内容 | 具体值 | 危害 |
|---------|--------|------|
| 完整 SQL 语句 | `insert into sys_user(dept_id, user_name, password, create_by, create_time) values(...)` | 暴露表结构与字段名 |
| 服务器本地绝对路径 | `jar:file:/C:/projects/RuoYi-Vue/ruoyi-admin/target/ruoyi-admin.jar!/BOOT-INF/lib/ruoyi-system-3.9.2.jar` | 暴露部署路径与 jar 结构 |
| 内部包名 + 类名 + 方法 | `com.ruoyi.system.mapper.SysUserMapper.insertUser` | 暴露内部架构 |

## 根因（源码证据链）

四环全部命中，属**必现**缺陷：

1. **校验层放行** — `SysUser.java` 的 `getNickName()` 仅 `@Xss` + `@Size(min=0,max=30)`，**无 `@NotBlank`**
2. **空值被 SQL 过滤** — `SysUserMapper.xml` 的 `<if test="nickName != null and nickName != ''">nick_name,</if>`，昵称为空时 INSERT 语句不含 `nick_name` 列
3. **数据库列非空** — `ry_20260417.sql` 的 `nick_name varchar(30) not null`（无默认值）
4. **异常信息回传前端** — `GlobalExceptionHandler.java` 的 `handleRuntimeException` 返回 `AjaxResult.error(e.getMessage())`

对应源码位置：

| 环节 | 文件 | 行号 |
|------|------|------|
| 校验放行 | `ruoyi-common/.../entity/SysUser.java` | 135-139 |
| 空值过滤 | `ruoyi-system/.../mapper/system/SysUserMapper.xml` | 151 |
| 列非空约束 | `sql/ry_20260417.sql` | 46 |
| 异常回传 | `ruoyi-framework/.../exception/GlobalExceptionHandler.java` | 96-102 |

## 修复建议

1. `SysUser.getNickName()` 补 `@NotBlank(message = "用户昵称不能为空")`
2. 全局异常处理器兜底分支返回统一友好提示（如"系统异常，请联系管理员"），生产环境不返回 `e.getMessage()` 原始异常

## 自动化用例

对应 [用户管理用例pytest.py](../代码/用户管理用例pytest.py) 中的 `test_user_add_empty_nickname`（参数化 `[None, '']`），断言 `code==500` 且 msg 含 `nick_name`，实测 **2 passed**。
