# 合并表头网页的关系化采集与映射版本

本工具用于查看授权来源的数据及其原始边界，样例中的机构、设备、人员和标识均为虚构。除旧的纯文本预览外，现提供可复核的结构化采集：解析合并表头与显式 headers 关联，登记绑定结构签名与适用单位的字段映射，输出采样点、项目、时段、数值和单位之间的关系，并保存足以回到源表单元格的定位信息。

## 目录

`source.py` 提供可重复的本地来源；`reader.py` 是旧的纯文本预览；`grid.py` 把表格展开成网格并解析表头关联；`interpret.py` 判读数值、单位与结构签名；`mapping.py` 校验并落实字段映射；`store.py` 持久化映射版本、页面状态与事实；`pipeline.py` 串联解析、映射与存储，提供待确认与对比视图；`app.py` 是入口；`fixtures/source.json` 可替换为同结构样例；`docs/数据约定.md` 描述接口与数据含义。

## 运行

使用 Python 3.11 及标准库，无第三方依赖。

```bash
python3 app.py                          # 演示：合并格、脚注、结构变更、单位漂移（临时状态库）
python3 app.py preview                  # 旧的纯文本预览
python3 app.py --state state collect    # 采集全部页面
python3 app.py --state state register '{"name":"沿江日报","signature":"sig-…","target_unit":"mg/L","units":{"mg/L":1.0},"fields":{"site":{"from":"row-header"},"project":{"from":"column-header","require":"unit"},"period":{"from":"column-header","require":"period"}}}'
python3 app.py --state state pending    # 查看待确认页面
python3 app.py --state state compare /v1
python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/collector-pycache python3 -m compileall -q app.py reader.py source.py grid.py interpret.py mapping.py store.py pipeline.py tests
```

## 容器

基础镜像固定摘要，不在启动阶段安装软件或获取远程数据。

```bash
docker build --pull=false -t table-grid:local .
docker run --rm --network none table-grid:local
docker run --rm --network none table-grid:local python3 -m unittest discover -s tests -v
```

## 本机演示

在全新临时目录执行 `python3 app.py` 可查看演示：合并格与脚注的还原、结构变更后旧映射不沿用、μg/L 到 mg/L 的换算、多指标共享时段的完整表头路径、未知单位拒绝入库，以及更换映射前后两版事实的对比。随后运行测试以观察来源边界。这两步使用本地小尺寸材料，通常数秒结束，不需要账户、设备或外部站点。持久化数据应放在 `state/` 或调用方明确传入的目录，不写入样例文件。
