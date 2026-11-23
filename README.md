# 海岚振动录制加工

Python 3.11 标准库应用，无网络和第三方依赖。从项目根目录运行：
```sh
python3.11 -B run.py verify
python3.11 -B run.py demo
```
verify 运行完整 unittest 套件，断言失败返回 1。demo 默认创建独立临时 SQLite 库，实际加工正常录制及缺测录制，打印逐事件新增点、封存 JSON、窗口指标和重开比对；业务错误返回 2。可用 `python3.11 -B run.py demo --db ./workday.sqlite` 保留库；已有演示任务有进度时明确拒绝重放。初始化只建立或检查版本 1，不清空、升级或回灌数据。同名标准库 wave 与本应用不同，请从项目根目录运行。

采集工程师的工作顺序是：
1. 登记通道、加速度单位和输入率，固定物理口径。
2. 登记转换任务、两个起点、输出率和相位系数表。
3. 接收首块，在现场读取已经确定的前缀。
4. 追加后续块，在同一绝对时间轴上持续交付。
5. 接收设备明确报告的缺测区间，区分无效点与真实零读数。
6. 按绝对输出位置范围读取已提交成果作复核。
7. 接受结束位置、补齐合法尾点并封存，导出供报告引用。
8. 质控员按半开时间窗口计算覆盖率和有效样本均方根。

上游是离线录制，样例见 samples/day.json。接纳只支持有序连续追加，不推断未声明缺测；不实现设备通信、多通道同步或滤波器设计。

## 公开 API

```python
from wave import (
    ArchiveRepository, register_channel, create_task, EXAMPLE_FILTER,
    SampleBlock, GapEvent, EndEvent, push_event, read_waveform,
    export_waveform, compute_windows, read_window_results,
)

with ArchiveRepository(":memory:") as repo:
    register_channel(repo, "bearing", "m/s²", 3)
    create_task(repo, "trial", "bearing", 0, 0, 2, EXAMPLE_FILTER)
    first = push_event(repo, "trial", SampleBlock(0, [2, 4]))
    middle = push_event(repo, "trial", SampleBlock(2, [6, 8, 10]))
    tail = push_event(repo, "trial", EndEvent(5))
    snapshot = read_waveform(repo, "trial", start=0, stop=4)
    exported_json = export_waveform(repo, "trial")
    batch = compute_windows(repo, "trial", [(0, 1), (1, 2)])
    saved_batch = read_window_results(repo, batch.batch_id)
```

register_channel(repo, channel_id, unit, input_rate) 和 create_task(repo, task_id, channel_id, input_start, output_start, output_rate, filter_spec) 返回不可变定义。同 ID 同规范内容幂等，不同内容抛 ValueError，不覆盖已有进度。缺通道抛 KeyError。FilterSpec / PhaseKernel 或 JSON 相位表均可传入；每相位为 phase 与有限的 [整数偏移, 有理系数] 列表。必须覆盖全部可达相位，偏移不重复，不自动插值、设计或归一化。

时间和率接受 int、Fraction 或 [整数分子, 非零整数分母]，不接受 float 和 bool；率必须正。输入位置是非负 int。样本为有限 int、float 或 Fraction，接纳后采用有限双精度实数。SampleBlock 非空，GapEvent 长度正。push_event(repo, task_id, event) 也接受样例中的 JSON 事件，返回新增 OutputPoint 的不可变 tuple。CaptureSession(repo, task_id).push_event(event) 是相同流式入口。

事件 start 必须等于当前前沿；前跳、倒退、重叠、非法样本、错误结束位置和结束后任何事件均抛 ValueError，不改变状态。缺任务抛 KeyError。每次输入、事件序号、输出、游标和封存标记共同提交；SQL 异常原样传播，重试与没有发生失败时一致。不会在内存中另存权威游标。单库连接用于顺序离线操作，不提供线程共享 API。

read_waveform(repo, task_id, start=None, stop=None) 返回独立 WaveformSnapshot，含 points、sealed、next_index、source_id。位置范围为半开区间，未发布位置不补造；反向、负数或非整数范围抛 ValueError。repo.iter_waveform 返回可 close 的独立快照迭代器，返回前 SQL 游标已经关闭。读取不计算转换。source_id 是固定口径和该次完整已提交成果的 SHA-256；活跃前缀变化时摘要变化，封存后固定。

export_waveform(repo, task_id) 仅接受封存任务，返回排序确定的 JSON 字符串。未封存抛 ValueError，缺任务抛 KeyError。包含固定口径、单位、绝对位置、时间、数值、有效性和 source_id。外部时间和系数均显式编码为规范分子分母数组；库内统一 codec 使用 $r 标记保留 Fraction。重开读取和导出不调用转换。

compute_windows(repo, task_id, windows) 返回并保存 WindowBatch，results 按请求顺序包含 task_id、source_id、ordinal、window、total、valid_count、coverage、rms。窗口是 TimeWindow 或两个有理端点，a<=b，选择 a<=time<b。保留重复窗口和空批次。覆盖率 k/n，n=0 时为 Fraction(0)；rms 只用 k 个有效值，k=0 时为 None。缩放和稳定求和避免平方溢出，手算正常例误差不超过 1e-10。未封存、反向或非法窗口抛 ValueError，缺任务抛 KeyError；整批保存或整批回滚。read_window_results(repo, batch_id) 读取固定已存指标，不重算。

## 时间与支持域

输入时间 ti+n/ri，输出时间 tm=to+m/ro，m 为非负整数。首个 m 满足 tm>=ti。对 u=(tm-ti)*ri，b=floor(u)，p=u-b，计算 sum(h(p,j)*x[b+j])。所有网格、相位及边界由 Fraction 精确决定。运输块不会重启相位。

非零系数位置共同决定时间、数值、有效性和可交付性。负输入位置为起始补零；结束确认后 n>=N 为结束补零。确认缺测为另一种状态，使对应输出 value=null、valid=false；未到达位置则保持待定。零系数不阻塞、不传播缺测。即使已有缺测，其他非零支持仍未确定时也不提前交付。每次只发布当前确认时间范围内的最长确定连续前缀，遇到第一个待定点停止。后续事件不修改旧点。

结束于 N 后仅保留 ti<=tm<ti+N/ri，不产生额外振铃区间；空输入封存为空成果。采集中同样要求 tm 小于当前前沿时间，防止交付最终不属于任务范围的点。

公开样例 ri=3、ro=2、ti=to=0，偏移 [-1,0,1]：
- 相位 0：[1/4,1/2,1/4]。
- 相位 1/2：[0,1/2,1/2]。

[2,4,6,8,10] 结束于 5，时间 [0,1/2,1,3/2]，值 [2,5,8,5]。先 [2,4] 交付 1 点，后续块交付 2 点，结束交付 1 点。位置 2 缺测时值为 [2,null,null,5]；[0,3/2) 覆盖率 1/3、rms=2，[1/2,3/2) 全无效、rms=null。位置 0 缺测而位置 1、2 为 4、6 时，时间 1/2 的值仍是有效 5，该相位在位置 0 的权重为零。正常窗口 [0,1) 的 rms=sqrt(29/2)。

## 实现与回归

catalog/validation、timegrid、filters、channels、tasks 管固定口径；assembly/events、segments、coverage、session、replay 管输入事实及一天驱动；conversion/kernel、support、output、processor 管加权支持和确定前缀；archive/codec、schema、repository、publish、export 管原子固定交付；quality/windows、selection、reducers、results、service 管封存成果的窗口消费。

tests/test_capture.py 覆盖手算网格、全部 16 种五点分块、较长正负序列、前缀不变、非法接纳及范围读取。test_support.py 覆盖未到达到缺测的交接、零权重、补零和完整支持等待。test_delivery.py 覆盖结束尾部、空输入、精确重开、无计算读取、多个真实 SQL 失败位置、重试和提前关闭。test_catalog.py 覆盖固定绑定与一般有理相位轨道。test_quality.py 覆盖半开窗口、来源绑定、空和全无效、稳定 RMS 与整批回滚。test_archive.py 覆盖编码、版本检查、磁盘回滚重开及真实离线样例。

完整独立命令：
```sh
python3.11 -B -m unittest discover -s tests -t . -v
```
测试使用内存库及自己创建的测试临时目录。SQL 失败由 SQLite 临时触发器真实产生；独立参照不调用生产网格、支持或转换算法。POINTWISE_SCENARIO 行在相关业务断言通过后输出实际值与独立预期，供核账读取。
