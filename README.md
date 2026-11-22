# 行道树风险处置采证台

离线采录行道树档案、巡查证据、处置许可、现场作业和独立复查。所有人物、树号与机构都是合成样例；程序不访问网络。项目以 Python 标准库和 SQLite 运行，原始 JSON 字节、引用文件的 SHA-256、业务裁定及当前投影分别持久化。

## 安装、演示与验证

```powershell
python -m pip install . --no-deps --no-build-isolation
python -m treecase demo --db demo.db
python -m treecase audit --db demo.db
python -m treecase report --db demo.db
python -m unittest discover -s tests -v
```

演示读取 `treecase/fixtures` 下 29 条合成来源事件，输出树木、许可、作业数量和各类裁定计数。重复运行演示时须传 `--force`，或者使用新数据库路径。`audit` 从不可变来源重新计算并与所有当前投影比较，同时核对仓库 fixture 资产哈希。

## 三个业务子系统

| 子系统 | 入口 | 持久化状态 | 可观察决定 |
| --- | --- | --- | --- |
| 树体档案与巡查 | `tree-import` | 身份、档案版次、证据哈希、风险及封控范围 | 身份冲突冻结；双人新鲜证据确立风险；后到复测扩大封控半径 |
| 处置许可与封控 | `permit-import`、`permit-revoke` | 申请、签章资产哈希、批准或拒绝、撤销 | 保护树授权、封控时效、风险版次、同树冲突占用决定是否许可 |
| 作业履约与复查 | `work-import` | 回执、截枝量、独立复查、销案状态 | 作业时点与许可范围、现场封控、复查见证决定接收、挂起或争议 |

来源事件保留原字节，业务不通过修改事件纠错。每次导入在一个事务中重放事件，重新生成三套投影；重复的同字节事件幂等返回，复用事件 ID 的不同字节会拒绝。格式或截枝数量无效会回滚整个导入。按来源时间排序使晚到数据的结论可重现。

## 单条正常与失败路径

```powershell
python -m treecase tree-import --db case.db --file treecase/fixtures/tree/t101_initial.json
python -m treecase permit-import --db case.db --file treecase/fixtures/permit/t101_prune_normal.json
python -m treecase tree-import --db case.db --file treecase/fixtures/tree/t101_late_urgent.json
python -m treecase permit-import --db case.db --file treecase/fixtures/permit/t101_emergency.json
python -m treecase work-import --db case.db --file treecase/fixtures/work/t101_complete.json
python -m treecase report --db case.db
```

以上路径从高风险升级为紧急风险，封控半径由 12 米升至 30 米。基于新版风险的许可和现场作业被接收，独立复查解除封控；作业附带的有效反证又把当前风险从紧急级重裁为低级，并保留旧风险及证据依据。示例异常：

```powershell
python -m treecase tree-import --db case.db --file treecase/fixtures/tree/t601_identity_base.json
python -m treecase tree-import --db case.db --file treecase/fixtures/tree/t601_identity_conflict.json
python -m treecase permit-import --db case.db --file treecase/fixtures/permit/t201_protected_remove_denied.json
```

身份冲突会入账为 `identity_conflict` 并保留旧主档；缺少树档的许可会被拒绝并留下明确原因。要验证保护树专项授权，应先导入 `tree/t201_protected.json`。业务拒绝的命令退出码为 0，因为它是有效来源的裁定结果；格式或证据资产错误的命令退出码为 2。

## 决策面与跨系统链路

1. 树位身份冲突冻结归属；同版档案不覆盖旧版。
2. 巡查需要两名独立采证者，照片或文本资产必须存在并记录哈希。
3. 过期证据不能升级风险；后到有效复测可改变风险版次。
4. 高风险与紧急风险产生不同的封控半径及有效期。
5. 保护树的修剪或移除需要专项授权。
6. 许可签发必须落在有效封控内，签章与申请时间需有效。
7. 同树重叠有效期的冲突处置许可只批准先到的一份。
8. 作业时点需要许可已批准、处于有效期且风险版次未过期。
9. 实际截枝数量和直径必须在许可范围内；无效数量整笔回滚。
10. 独立复查决定销案，现场反证可重裁树体风险；许可撤销会把先前接收的作业转成争议，撤回其反证结论并恢复封控。

树体档案影响许可，许可和封控影响作业，作业复查及现场反证再次改变树体状态。这些关系由 `tree_policy.py`、`permit_policy.py`、`work_policy.py` 经 `engine.py` 的重放实现；`report.py` 展示当前状态与每条来源的历史裁定及规则版本。巡查、证据、封控令和复查也有可查询的 SQLite 记录。

## 外审证据封包

`review-packet` 在不交出巡查员名册的前提下，把某一版许可裁决打包给外部复核人：

```powershell
python -m treecase review-packet --db case.db --permit PER-101-NORMAL --constraints fixtures/review_packet_constraints.json --attestations fixtures/review_packet_attestations.json
```

封包通过 `engine.py` 重放原件取得内部快照，并明确绑定所查裁决（许可号、风险版次、裁决引用与快照摘要）。同一申请在树档新版下会被重新试审（例如急险版下得到 `STALE_RISK_REVISION`），旧封包仍按自己的快照复查，新版批复不会改写旧包。包内时间是同一合法原点下的秒偏移，外审用与内部相同的规则复算树体等级、证据新鲜度、封控窗与许可结论。

合同准许两条交付路线：

* `expanded`：同一受控卷宗内可比对的双见证代号与经批准的附件投影，供能继续逐份查验原件的监督员使用；签发前把已交付旧包的公开约束与新包将暴露的约束合并，枚举整体身份解释，任一受限见证人只剩一种可能时拒绝签发并留待人工。
* `relationship-only`：范围更窄的封闭复核凭独立签认员在同一裁决引用下出具的关系凭据复核许可；凭据只承诺两份已校验原件的互异性、实际等级输入与可复算的有效时间差，签认员不能充当两名采集者之一，版次不符、原件未核验或凭据缺失时不得用匿名代号数冒充互异证明。

已交付的包不可撤回，也不能假装外审没读过其中某一列：匿名性分析始终并集旧包约束。匿名替换不会掩盖两份原件出自同一人——同一上传者只得到一个代号。拒绝签发是业务结果，退出码为 0；未知许可等用法错误退出码为 2。

## 源码边界

采录的是合成离线证据，不验证真实机构签章或真实地理坐标。封控半径是演示业务规则，不代表实际市政安全标准。原始事件不可修改或删除；当前投影可重建，`audit` 可发现其被外部改动。
