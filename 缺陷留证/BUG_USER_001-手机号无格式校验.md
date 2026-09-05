# BUG_USER_001 — 新增用户手机号输入 11 位字母仍能保存成功

## 基本信息

| 项目 | 内容 |
|------|------|
| Bug 编号 | BUG_USER_001 |
| 标题 | 新增用户手机号输入 11 位字母仍能保存成功 |
| 模块 | 用户管理 |
| 严重程度 | 一般 |
| 状态 | 已确认（已复现） |
| 复现日期 | 2026-09-05 |
| 复现环境 | Spring Boot 2.5.15 + MySQL 8.0（ry_vue 库） |

## 复现步骤

1. 以 admin/admin123 登录获取 token
2. `POST /system/user`，`phonenumber` 填 11 位字母 `abcdefghijk`
3. 观察响应 + SQL 核对

## 请求

```
POST http://localhost:8080/system/user
Authorization: Bearer {token}
Content-Type: application/json

{
  "userName": "test_phone_letters",
  "nickName": "手机号字母",
  "deptId": 103,
  "password": "12345",
  "phonenumber": "abcdefghijk"
}
```

## 真实响应（实测抓取）

```json
{
  "code": 200,
  "msg": "操作成功"
}
```

## SQL 核对

```sql
SELECT phonenumber FROM sys_user WHERE user_name='test_phone_letters';
-- 结果：abcdefghijk（11 位字母已落库，未被拦截）
```

## 根因（源码证据链）

`SysUser.java` 的 `getPhonenumber()` 只有 `@Size(min=0, max=11)` 长度校验，**没有 `@Pattern` 正则校验**，导致字母也能通过校验并保存。

| 环节 | 文件 | 行号 |
|------|------|------|
| 仅长度校验、无正则 | `SysUser.java` | 171-175 |

```java
@Size(min = 0, max = 11, message = "手机号码长度不能超过11个字符")
public String getPhonenumber()
{
    return phonenumber;
}
```

## 修复建议

补 `@Pattern` 数字正则，例如：

```java
@Pattern(regexp = "^1[3-9]\\d{9}$", message = "手机号格式不正确")
```

或至少 `@Pattern(regexp = "^\\d{11}$", message = "手机号格式不正确")`。

## 自动化用例

对应 [用户管理用例pytest.py](../代码/用户管理用例pytest.py) 中的 `test_user_add_phone_letters`，断言 `code==200` 且库中 `phonenumber=='abcdefghijk'`。
