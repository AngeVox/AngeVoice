# AngeVoice v2.6.616 Release Notes

## AngeVoice 2.6.616

AngeVoice 2.6.616 是 Web Studio API Key 访问记忆的热修复版本。

### 修复

- 修复 Web Studio 显示"已在此浏览器保存访问会话"，但点击合成仍要求填写 Bearer Token 的认证死循环。
- Studio 现在会正确使用安全的 HttpOnly Cookie 会话完成同源合成请求认证。
- 刷新或重新打开 Studio 页面后，只要访问 Cookie 仍有效，就无需重新输入 API Key。
- 清除 Cookie、点击移除访问或轮换 API Key 后，会正确要求重新输入 API Key。
- 本修复不会恢复 localStorage 明文保存 API Key。

---

## AngeVoice 2.6.616

AngeVoice 2.6.616 is a hotfix release for Web Studio API Key access persistence.

### Fixed

- Fixed a Web Studio authentication loop where the page reported that API Key access was saved in the browser, but synthesis requests were still blocked by the client-side Bearer Token check.
- Studio API Key access now correctly uses the secure HttpOnly Cookie session for same-origin synthesis requests.
- Refreshing or reopening the Studio page no longer requires re-entering the API Key while the access Cookie remains valid.
- Clearing cookies, removing access, or rotating the API Key correctly requires entering the API Key again.
- The fix does not restore localStorage plaintext API Key persistence.

### Docker and fnOS

Docker images and fnOS package use v-prefixed version tags:

- `maxblack777/angevoice-cpu:v2.6.616`
- `maxblack777/angevoice-gpu:v2.6.616`
- `maxblack777/angevoice-legacy-gpu:v2.6.616`

### Notes

- This is a hotfix for v2.6.615. See v2.6.615 release notes for the full feature and security update details.
- Supported Python versions remain 3.10–3.12.
