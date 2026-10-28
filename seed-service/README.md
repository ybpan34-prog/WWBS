# WWBS 在线种子库

公开接口：`https://wwbs-seed-library.netlify.app/.netlify/functions/seeds`

软件只上传当前生成的战斗轴种子。服务校验WWBS4／WWBS5格式、名称长度、校验码、角色顺序、驻场时间与模块参数后保存；数据为公开共享内容。WWBS5支持F键处决与技能／大招按次数施放；旧格式的模块索引与参数保持不变。

## 接口

- `POST`，JSON `{"seed":"【名字】WWBS4.…"}`：上传或返回相同名称、相同轴的已有条目。兼容旧的`【名字】4.…`，两种前缀保持相同种子身份。
- `GET ?name=关键词`：名称包含检索，按上传时间从新到旧显示最多50项，未填名称时浏览最新上传。检索先按时间排序再截取50项；兼容已有记录，无需重新上传。单次扫描上限5000条索引，超出或结果多于50条时返回`truncated`。
- `GET ?id=条目编号`：下载完整种子。
- `GET ?health=1`：健康检查。

种子对象与检索索引使用Netlify Blobs持久保存。索引按记录独立创建，避免共享索引的并发覆盖；可在上传失败后重试补齐索引。函数提供请求大小和访问频率限制。

## 维护

在本目录执行 `npm ci` 和 `npm test`。部署使用Netlify CLI，项目ID：`157c28f8-ec69-49f9-b68b-26fe4e5ddcc1`。

预览：`npx netlify deploy --site 157c28f8-ec69-49f9-b68b-26fe4e5ddcc1 --build`。

发布：`npx netlify deploy --site 157c28f8-ec69-49f9-b68b-26fe4e5ddcc1 --build --prod`。

`.netlify`目录和部署授权不提交到源码。生产使用固定存储名，不在预览部署中写入测试数据；单元检查使用内存存储。


## 安装包下载中转

`GET /.netlify/functions/update-download?tag=v1.5.6&id=资源ID&size=总字节数&sha256=官方校验码`，必须提供严格的`Range: bytes=开始-结束`，每段最多4MB。只读取固定WWBS仓库中的正式版本安装包，拒绝任意上游URL。桌面客户端直接从GitHub获取资源身份与SHA256，比较下载线路后使用中转或直连；中转不提供更新元数据、不决定安装包是否可信，客户端合并后仍核对官方SHA256。中转不接收本地设置。避免每段重复消耗GitHub匿名元数据API额度。
