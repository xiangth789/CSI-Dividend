中证红利低波50 在线稳定版（自动部署版）

部署：
1. GitHub 新建 Public 仓库。
2. 上传本压缩包全部内容，必须保留 .github/workflows/update.yml。
3. Settings → Actions → General → Workflow permissions：
   选择 Read and write permissions，保存。
4. Settings → Pages → Build and deployment：
   Source 选择 GitHub Actions。
5. Actions → Update and deploy dividend-low-vol dashboard → Run workflow。
6. 等待任务变成绿色。
7. 回到 Settings → Pages，点击 Visit site。

以后：
- 周一至周五北京时间约 09:00–15:55，每5分钟尝试更新并直接部署。
- GitHub Actions 定时任务可能有数分钟延迟，因此属于准实时。
- iPhone：Safari → 分享 → 添加到主屏幕。
- Android：Chrome → 菜单 → 添加到主屏幕。
