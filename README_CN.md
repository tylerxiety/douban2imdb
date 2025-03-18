# 豆瓣到IMDb评分迁移工具

一个将您的豆瓣电影评分迁移到IMDb账户的Python工具。

## 功能特点

### 核心功能
- **豆瓣导出**：自动导出您的完整电影评分历史
- **IMDb导入**：匹配电影并将评分导入您的IMDb账户
- **智能匹配**：使用多种策略找到正确的IMDb对应影片
- **手动审核**：用户友好的界面，用于审核不确定的匹配

### 附加功能
- **电视剧支持**：正确处理多季电视剧
- **评分转换**：将豆瓣5星制转换为IMDb的10分制
- **断点续传**：可从中断处继续操作
- **代理支持**：可选代理配置，提高可靠性


## 安装

1. 克隆此仓库：
```bash
git clone https://github.com/tylerxiety/douban2imdb.git
cd douban2imdb
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 设置环境变量（可选）：
```bash
cp .env.sample .env
# 编辑.env文件，根据您的需求修改设置
```

4. 确保您已安装Chrome浏览器（用于Selenium网页驱动）。

## 使用方法

完整的迁移过程包含以下步骤：

1. 导出豆瓣评分
2. （可选）导出IMDb评分
3. 准备迁移方案
4. 执行迁移到IMDb

您可以分别运行每个步骤，或者使用主脚本按顺序运行所有步骤。

### 使用主脚本（推荐）

主脚本会按正确顺序自动运行所有步骤：

```bash
python src/main.py
```

您也可以运行特定步骤：

```bash
python src/main.py --step export_douban  # 仅导出豆瓣评分
python src/main.py --step export_imdb     # 仅导出IMDb评分（可选）
python src/main.py --step prepare         # 仅准备迁移计划
python src/main.py --step migrate         # 仅执行迁移
```

### 步骤1：导出您的豆瓣评分

```bash
python src/douban_export.py
```

此命令将：
1. 打开Chrome浏览器
2. 要求您手动登录豆瓣
3. 自动检测您的用户ID（如果检测失败则需要手动输入）
4. 抓取您的所有电影评分
5. 从豆瓣电影页面直接提取IMDb ID（如果可用）
6. 将结果保存到`data/douban_ratings.json`

#### 填充缺失的IMDb ID

如果某些电影无法自动提取IMDb ID：

```bash
python src/douban_export.py --fill-missing-imdb
```

#### 手动匹配复杂情况

对于无法自动找到IMDb ID的电影：

```bash
python src/manual_imdb_match.py
```

这个交互式工具将：
1. 显示每部缺少IMDb ID的电影
2. 让您直接搜索IMDb
3. 允许您输入正确的IMDb ID

### 步骤2：（可选）导出您的IMDb评分

```bash
python src/imdb_export.py
```

此可选步骤将：
1. 打开Chrome浏览器
2. 要求您手动登录IMDb
3. 导出您现有的IMDb评分到`data/imdb_ratings.json`

这有助于加快迁移过程，因为系统会识别出您已经在IMDb上评分过的电影并跳过它们。如果您跳过此步骤，迁移仍然可以工作，但在迁移过程中需要检查每部电影是否已经评分。

### 步骤3：准备迁移计划

生成一个将评分迁移到IMDb的计划：

```bash
python src/prepare_migration.py
```

此过程会创建一个迁移计划，该计划：
- 识别需要迁移的电影
- 将多季电视剧分组
- 对电视剧评分进行平均化处理
- 处理重复条目

### 步骤4：执行IMDb迁移

最后，执行迁移以更新您的IMDb评分：

```bash
python src/migrate.py --execute-plan
```

迁移脚本将：
1. 打开Chrome浏览器
2. 要求您手动登录IMDb
3. 处理迁移计划中的每部电影
4. 使用您的豆瓣评分为IMDb上的电影评分
5. 保存迁移进度，以便在中断时可以恢复

## 电视剧处理

电视剧通过以下方式处理：

1. 基于标题相似性识别电视剧的各季
2. 将豆瓣上各季评分的平均分用作IMDb评分
3. 将豆瓣上第一季的IMDb ID作为正确的IMDb ID
4. 自动从剧集页面重定向到主节目页面

## 故障排除

如果您遇到连接问题：

1. 尝试增加超时时间：`--timeout 180`
2. 增加重试次数：`--retries 10`
3. 使用代理服务器：
   ```
   # 在.env文件中添加：
   PROXY=http://user:pass@host:port
   
   # 或在命令行中指定：
   python src/migrate.py --execute-plan --proxy "http://user:pass@host:port"
   ```
4. 启用速度模式以加快加载速度：`--speed-mode`
5. 在测试模式下运行以查看详细诊断：`--test-mode`

## 配置

脚本行为可以通过`.env`文件中的环境变量进行修改：

| 变量 | 描述 | 默认值 |
|----------|-------------|---------|
| `DOUBAN_EXPORT_PATH` | 评分保存路径 | `data/douban_ratings.json` |
| `DEBUG_MODE` | 启用详细日志 | `False` | 
| `THROTTLING_ENABLED` | 启用请求节流 | `False` |
| `FAST_MODE` | 跳过非必要操作以提高速度 | `True` |
| `BROWSER_MAX_INIT_ATTEMPTS` | 浏览器初始化重试次数 | `3` |
| `CHROME_PATH` | Chrome可执行文件的可选路径 | 系统默认 |
| `MIN_PAGE_DELAY` | 页面加载之间的最小延迟（秒） | `0.0` |
| `MAX_PAGE_DELAY` | 页面加载之间的最大延迟（秒） | `0.2` |
| `START_PAGE` | 评分起始页码 | `1` |
| `MAX_PAGES` | 处理的最大页数（0表示无限制） | `0` |
| `PROXY` | 代理服务器，格式为http://user:pass@host:port | 无 |

查看`.env.sample`获取所有可用选项。

## 许可证

MIT

## 鸣谢

- [豆瓣](https://movie.douban.com/)
- [IMDb](https://www.imdb.com/)