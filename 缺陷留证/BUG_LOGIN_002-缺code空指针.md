# BUG_LOGIN_002 — 登录接口缺 code 字段返回 msg=null（空指针）

## 基本信息

| 项目 | 内容 |
|------|------|
| Bug 编号 | BUG_LOGIN_002 |
| 标题 | 登录接口缺 code 字段返回 msg=null（空指针） |
| 模块 | 登录 |
| 严重程度 | 一般 |
| 状态 | 已确认（已复现） |
| 复现日期 | 2026-09-05 |
| 复现环境 | Spring Boot 2.5.15 + MySQL 8.0 + Redis |

## 复现步骤

1. `GET /captchaImage` 获取有效 uuid
2. `POST /login`，请求体只传 username、password、uuid，**不传 code 字段**
3. 观察响应

## 请求

```
POST http://localhost:8080/login
Content-Type: application/json

{
  "username": "admin",
  "password": "admin123",
  "uuid": "{上一步拿到的 uuid}"
}
```

## 真实响应（实测抓取）

```json
{
  "code": 500,
  "msg": null
}
```

前端无任何友好提示，用户只看到一片空白或通用错误页。

## 根因（源码证据链）

四环命中，属**必现**缺陷：

1. **参数无校验** — `LoginBody.java` 的 `code` 字段无 `@NotBlank` 等校验注解
2. **接口未开启校验** — `SysLoginController.login` 的 `@RequestBody LoginBody loginBody` 未加 `@Valid`
3. **空指针** — `SysLoginService.validateCaptcha` 第 123 行 `code.equalsIgnoreCase(captcha)` 对 null 直接空指针
4. **msg 为 null** — `GlobalExceptionHandler.handleRuntimeException` 返回 `AjaxResult.error(e.getMessage())`，而 NPE 的 message 为 null，故响应 msg=null

| 环节 | 文件 | 行号 |
|------|------|------|
| code 无校验 | `LoginBody.java` | 23 |
| 未加 @Valid | `SysLoginController.java` | 57-62 |
| 空指针 | `SysLoginService.java` | 123 |
| 异常回传 | `GlobalExceptionHandler.java` | 96-102 |

## 修复建议

1. `LoginBody.code` 补 `@NotBlank(message = "验证码不能为空")`
2. 或 `SysLoginController.login` 参数加 `@Valid` 开启参数校验
3. `validateCaptcha` 对 code 做空值判断，返回友好提示

## 自动化用例

对应 pytest 用例中「缺 code 字段」场景，断言 `code==500` 且 `msg==null`。
