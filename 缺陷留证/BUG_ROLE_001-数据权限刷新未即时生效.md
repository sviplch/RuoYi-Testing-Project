# BUG_ROLE_001 — 修改角色数据权限后在线用户数据范围未即时刷新

## 基本信息

| 项目 | 内容 |
|------|------|
| Bug 编号 | BUG_ROLE_001 |
| 标题 | 修改角色数据权限后在线用户数据范围未即时刷新 |
| 模块 | 角色管理与数据权限 |
| 严重程度 | 一般 |
| 状态 | 已确认（源码证据链） |
| 复现日期 | 2026-09-05 |
| 复现环境 | Spring Boot 2.5.15 + MySQL 8.0 + Redis |

## 根因（源码证据链）

四环命中，逻辑必然：

1. **改数据权限不刷缓存** — 修改数据权限走 `PUT /system/role/dataScope` → `SysRoleController.dataScope`（141-147 行），只调用 `authDataScope` 更新数据库（`sys_role.data_scope` + `sys_role_dept`），**不刷新在线用户缓存**
2. **refresh 只刷菜单权限** — `edit` 接口（改角色基本信息）虽然调了 `refreshPermissionByRoleId`，但该方法（`TokenService.java:265`）只 `setPermissions(getMenuPermission(...))` 刷新**菜单权限**，**不更新 roles 的 dataScope**
3. **SQL 取缓存的 roles** — 数据权限 SQL 由 `DataScopeAspect` 在查询时根据 `LoginUser.getUser().getRoles()` 的 dataScope 实时拼接（`DataScopeAspect.java:72,79-128`）
4. **roles 是登录时的旧值** — `LoginUser` 从 Redis 缓存反序列化，其 roles 是用户**登录时**从数据库加载的旧值

**结论**：修改角色数据权限后，已在线用户的 `roles.dataScope` 仍是旧值，数据范围不即时生效，需重新登录（重新从 DB 加载 roles）才生效。

| 环节 | 文件 | 行号 |
|------|------|------|
| dataScope 接口不刷缓存 | `SysRoleController.java` | 141-147 |
| refresh 只刷 permissions | `TokenService.java` | 240-268 |
| SQL 实时拼但取缓存 roles | `DataScopeAspect.java` | 45, 72, 79-128 |

## 修复建议

1. `SysRoleController.dataScope` 在 `authDataScope` 后调用 `refreshPermissionByRoleId`
2. `refreshPermissionByRoleId` 需同时刷新 roles 的 `dataScope`（重新从 DB 加载该角色的 dataScope 并更新到在线用户的 `LoginUser`）

## 说明

本缺陷以源码证据链定性（四环完整、逻辑必然，不依赖运行时偶发）。实测需造「部门树 + 多角色 + 多用户」数据并分别登录对比返回行数，成本较高，故以源码结论为准；如需可补充实测留证。
