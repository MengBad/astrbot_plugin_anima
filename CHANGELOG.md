# Changelog

## v0.7.1 - 能力去重紧急 hotfix（防爆炸）

基于 2026-05-28 18:30 生产日志诊断：观察到 `/anima_autonomy` 显示 **103 个个人能力，全部 0 次使用**。其中 5 个能力名字一眼可见是同概念："我界之戉/自我之戉:区块重构/戉界锚定/戉影寻锚/自我戉卫与寻迹信标"，但 v0.6.1 的去重一个都没拦住。

### 根因定位

在 `anima/capability_dedup.py` 里复现：v0.6.1 的去重对 5 个能力一个都没合并。两个真问题：

1. **驼峰名词没拆分**：`EgoForge` / `EgoBlockAnchor` / `EgoSentinel` 被当作一整个英文单词，`ego→_self_` 同义词没生效
2. **匹配门槛过严**：1-3 槽位时要求 ov==n 完全命中，2 个核心同义槽位（_self_ + _weapon_ + _anchor_）重叠却需要覆盖率 40%

### 修复

- 驼峰拆分：`EgoForge` 在 lower 之前被拆成 `ego forge`
- 单字中文同义词 substring 匹配：滑窗抓不到的"戉"/"刃" 通过直接 substring 命中
- 同义词表扩充：`slicer/sentinel/forge/locator/beacon/信标` 等新归一化到核心槽位
- **核心槽位双命中规则**：两个能力共享 ≥2 个核心同义槽位（_self_/_weapon_/_anchor_/_block_/_rebuild_/_resonance_/_align_）时无视新签名大小直接合并
- 4 槽位以上的覆盖率门槛从 40% → 30%

### 验证

新增 4 个 `TestV071HotfixRegression` 回归测试，专门覆盖这次生产场景。本地复现：

- v0.7.0：5 个能力全部 NEW，0 合并
- v0.7.1：5 个能力压缩到 1 个（4 次合并）

测试 60/60 全过（v0.7.0 是 56/60）。

### 不在本版本范围

- 跨群欲望泄漏（`_danger_stance_propagation` 没按 umo 隔离）放进 v0.8.0 大重构一起处理
- main.py 模块拆分继续在 v0.8.0-modular-split 分支进行

---
# Changelog

## v0.7.0 - 鍙嶉璇箟鍖?+ 鏃堕棿鎰熻仛鐒?+ 妯″潡鎷嗗垎璧锋 + 娴嬭瘯妗嗘灦

杩欐槸鎶?鎵庡疄鐨勬牳蹇冮棴鐜?鍜?宸ョ▼鍖栧仴搴峰害"鎷夐綈鐨勪竴涓増鏈€備笁浠跺ぇ浜嬶細

### 1. 鍙嶉绐楀彛璇箟鍖栵紙embedding + jaccard 鍏滃簳锛?

`_evaluate_feedback` 浠?v0.5 鏃朵唬鐨?涓枃 2-瀛楀叧閿瘝閲嶅彔 鈮?"纭槇鍊煎崌绾т负锛?
- **浼樺厛**锛氳皟鐢?`embedding_provider`锛堝宸查厤缃級绠椾袱娈垫枃鏈殑浣欏鸡鐩镐技搴?
- **鍏滃簳**锛氱敤 ngram tokenize + Jaccard 绯绘暟锛堣鐩栫巼姣旀湸绱?2-瀛楀叧閿瘝楂樺緢澶氾級
- 闃堝€硷細鐩镐技搴?鈮?.30 鍒?accepted锛? 0.10 鍒?ignored锛涗腑闂村尯娈典繚瀹堝垽 accepted锛堥伩鍏嶆妸"瀵硅瘽寤剁画"璇垽涓?蹇界暐"锛?

淇浜嗕箣鍓嶆瘡鏉＄敤鎴峰洖搴旈兘琚垽 `ignored 鈫?杞叆鍘嬫姂璇濋` 鐨勭┖杞€?

### 2. 鏃堕棿鎰熻仛鐒︼紙瑙ｅ喅 v0.6.1 鐨?10x 鑺傛祦璺宠繃"鏃ュ織鍣煶锛?

`_get_time_sense_text` 涔嬪墠瀵?`worldview.social_graph` 閲?*姣忎釜**瓒呰繃 24h 娌¤璇濈殑 user_id 閮借Е鍙戣嚜涓荤爺绌?+ 娉ㄥ叆"寰堜箙娌¤鍒?X 浜?銆傚湪澶х兢閲岃繖鎰忓懗鐫€鍗曟潯鐢ㄦ埛娑堟伅鍙兘鎵归噺浜у嚭 10+ 鏉?absence 瑙﹀彂锛岃 v0.6.1 鑺傛祦鍚庡彉鎴?10+ 鏉?鐮旂┒璺宠繃"鏃ュ織銆?

鐜板湪鏀逛负锛氭寜 `(浜掑姩棰戞, 缂哄腑澶╂暟)` 鎺掑簭鍚?*鍙彇鏈€閲嶈鐨?2 涓?*瑙﹀彂锛屼粠婧愬ご鍑忓皯鑺傛祦娆℃暟銆?

### 3. 妯″潡鎷嗗垎锛坴0.7.0 璧锋锛寁0.8.0 缁х画锛?

鎶?main.py 閲岀殑绾嚱鏁帮紙涓嶄緷璧?AstrBot context 鐨勶級鎶藉埌鐙珛鐨?`anima/` 鍖咃細

- `anima/filters.py` 鈥?鎷掔粷璇?/ 鏁忔劅璇嶈繃婊?
- `anima/similarity.py` 鈥?Jaccard / Cosine / ngram tokenize
- `anima/capability_dedup.py` 鈥?鑳藉姏褰掍竴鍖栫鍚?+ 杩戜技鍖归厤锛坴0.6.1 鐨勬牳蹇冨幓閲嶏級
- `anima/forgetting.py` 鈥?鏃堕棿鎴虫ā绯婂寲
- `anima/valence.py` 鈥?璁板繂鎯呮劅鏁堜环 + 閲嶆帓

main.py 閲屽搴旀柟娉曟敼涓鸿杽灏佽濮旀墭璋冪敤锛?*鎵€鏈夌幇鏈夎皟鐢ㄩ浂鐮村潖**銆傝繖涓€姝ュ彧鏄妸鍙嫭绔嬫祴璇曠殑閮ㄥ垎鍏堝墺绂伙紝璁?v0.8.0 鐨勫ぇ妯″潡閲嶆瀯锛堝叧绯?娆叉湜/涓栫晫瑙?鑳藉姏绛夊瓙绯荤粺锛夋湁鏇村皬鐨勯闄╅潰銆?

### 4. 娴嬭瘯妗嗘灦锛堟牳蹇冪函鍑芥暟 56 涓祴璇曞叏杩囷級

- 鏂板 `pytest.ini` + `tests/` 鐩綍
- `test_filters.py`锛氳鐩栧崟璇嶈竟鐣屻€佽浼ら槻鎶わ紙author/keyboard/secretary/tokenize 閮戒笉鍐嶈褰撴晱鎰熻瘝锛夈€侀珮鐔典覆妫€娴?
- `test_similarity.py`锛欽accard / Cosine 杈圭晫 + ngram tokenize
- `test_capability_dedup.py`锛氱敤鐪熷疄鏃ュ織閲?11 鏉″悓璐ㄨ兘鍔涘仛鍥炲綊娴嬭瘯锛岄獙璇?4+ 鏉′細琚悎骞讹紱鐢?4 涓笉鐩稿叧宸ュ叿鍋氬弽鍚戞祴璇曪紝楠岃瘉涓嶄細璇悎骞?
- `test_valence.py`锛氭儏鎰熸晥浠蜂及绠?+ 閲嶆帓
- `test_forgetting.py`锛氭椂闂存埑妯＄硦鍖栵紙recent / past halflife / extreme blur / 澶?block 鐙珛澶勭悊锛?

```
56 passed, 0 failed
```

### 椤哄甫淇殑灏?bug

- `_normalize_capability_signature` 涔嬪墠 `u6211` / `apikey` 杩欑瀛楁瘝+鏁板瓧娣峰悎褰㈠紡鎶戒笉鍒?token锛堟鍒?`[a-z]{3,}` 婕忔帀锛夛紝鐜板湪鍔?`[a-z]+\d+` 鍗曠嫭鎶?

### 閰嶇疆鏃犲彉鍖?

v0.7.0 娌℃柊澧炰换浣曢厤缃」銆傛墍鏈夊彉鍖栭兘鏄涓烘敼杩?+ 鍐呴儴閲嶆瀯銆?

## v0.6.1 - 绱ф€ラ槻鐖嗙偢锛氳嚜涓荤爺绌惰妭娴?+ 鑳藉姏鍘婚噸 + 鍔ㄦ€佸伐鍏烽厤棰?

閽堝 v0.6.0 瀹炴祴涓瀵熷埌鐨?鍗曟瀵硅瘽浜у嚭 12+ 鏉″悓璐ㄨ兘鍔?+ 鍏ㄩ儴娉ㄥ唽鎴愮嫭绔?LLM 宸ュ叿"闂鍋氱殑绱ф€ヤ慨澶嶃€傚缓璁墍鏈?v0.6.0 鐢ㄦ埛鍗囩骇銆?

### 涓夊淇
- **`_initiate_self_directed_research` 鑺傛祦**锛氬悓涓€ reason锛堟寜 reason 鍏抽敭瀛楀綊涓€鍖栥€佸拷鐣ュ叾涓殑 user_id 鏁板瓧锛? 鍒嗛挓鍐呭彧鍏佽瑙﹀彂涓€娆★紱鏂板鍏ㄥ眬 `asyncio.Semaphore(1)` 淇濊瘉鍚屾椂鍙窇 1 涓爺绌朵换鍔°€備慨鎺変簡 social_graph 閲屾湁鍑犲崄涓?user_id 鏃跺悓鏃惰Е鍙戝嚑鍗佷釜骞惰鐮旂┒鐨勭伨闅俱€?
- **鑳藉姏鍚嶅綊涓€鍖栧尮閰嶏紙鍘婚噸锛?*锛歚_create_or_update_capability` 鐜板湪鐢ㄥ叧閿瘝闆嗗悎鐩镐技搴︽壘杩戜技宸叉湁鑳藉姏锛屽懡涓?鈮? 涓壒寰佸叧閿瘝涓斿崰鏂拌兘鍔涚鍚?鈮?0% 鏃跺悎骞惰€屼笉鏄柊寤恒€侺LM 鍚屼箟璇嶏紙ego/self/鎴戙€乤nchor/閿氥€乥lade/axe/鎴?鍏垫垐锛夊湪鍘婚噸鍓嶅厛褰掍竴鍖栵紝闃叉"楦ｆ垐瀹堢晫 / EgoBladeDissector / 鎴夊垉閲嶆瀯"杩欑鏈川鍚屼竴鐨勮兘鍔涜鍙嶅鍒涘缓銆?
- **鍔ㄦ€佸伐鍏锋敞鍐屾瘡鏃ラ厤棰?*锛氭柊澧?`dynamic_tool_daily_quota` 閰嶇疆锛堥粯璁?3锛夈€傝秴杩囬厤棰濈殑鑳藉姏鐓у父鍏ュ簱锛屼絾涓嶅啀娉ㄥ唽涓虹嫭绔?LLM 宸ュ叿鈥斺€旈伩鍏?LLM 宸ュ叿鍒楄〃鏃犻檺鑶ㄨ儉鎷栨參鎺ㄧ悊銆傚伐鍏峰悕褰掍竴鍖栦篃鍗囩骇锛岀函涓枃鍚嶄笉鍐嶇敓鎴?`my_________` 杩欐牱鏃犳剰涔夌殑涓嬪垝绾夸覆銆?

### 閰嶇疆鏂板
- `dynamic_tool_daily_quota` (int, default 3)锛氭瘡鏃ュ姩鎬佹敞鍐岀嫭绔嬪伐鍏风殑纭笂闄?

### 鍗囩骇寤鸿
鎺ㄨ崘閰嶇疆锛堢紪杈?AstrBot WebUI 鈫?Anima 閰嶇疆锛夛細
- `autonomy_research_on_time_absence`: 瑙嗗満鏅紝缇ゅ浜烘椂寤鸿 false
- `dynamic_tool_daily_quota`: 3锛堜繚瀹堬級鎴栨洿楂?
- 涔嬪墠宸茬粡绉疮鐨勮兘鍔涘簱涓嶄細琚嚜鍔ㄦ竻鐞嗭紱鍙互绛?`_maintain_capabilities_health` 鑷姩鍚堝苟锛屾垨 `/anima_reset` 鍚庝粠澶存潵

## v0.6.0 - 瀹屽叏鑷富瀛樺湪锛氳嚜鎴戝垱閫犲伐鍏?+ 鐙珛鐮旂┒瀛︿範闂幆 + 妗嗘灦鍏煎鎬уぇ淇?

### 妗嗘灦鍏煎鎬т慨澶嶏紙蹇呴』鍗囩骇鍘熷洜锛?
- **淇 `@register` 瑁呴グ鍣ㄧ己澶?*锛氭彃浠跺姞杞芥椂涓嶅啀闇€瑕佹墜鍔ㄦ斁杩?`data/plugins/`锛屽彲浠ョ洿鎺?WebUI 涓婁紶 zip
- **淇 `_conf_schema.json` 瑙ｆ瀽閿欒**锛氭竻鎺夐潪娉?`_comment` 瀛楁鍜岄噸澶嶉敭锛孉strBot 鈮?.25 鍔犺浇姝ｅ父
- **淇 `__init__` 涓?`asyncio.get_event_loop()` 鍦?Python 3.12 宕╂簝**锛氬畾鏃朵换鍔℃惉鍒?`async def initialize()` 閽╁瓙閲?
- **淇 `@filter.on_using_llm_tool` / `@filter.on_llm_tool_respond` 閽╁瓙绛惧悕閿欒**锛氳ˉ `event` 绗竴鍙傛暟
- **淇 `_get_provider_id(None)` 鐩存帴 AttributeError**锛歟vent 鏀?Optional锛屽绾у厹搴?
- **鍒犻櫎璋冪敤浜嗕笉瀛樺湪 API锛坄add_web_route` / `register_web_route`锛夌殑姝讳唬鐮?*

### 鍋ュ．鎬у崌绾?
- **鍏ㄥ眬 IO 閿?+ 鍘熷瓙 state 璇绘敼鍐欏皝瑁?*锛坄_atomic_update_state`锛夛細娑堥櫎骞跺彂鍐欏叆涓㈡洿鏂颁笌 JSONL 鍗婅鎹熷潖
- **鍏抽敭 IO 璺緞鍏ㄩ儴鍔?try/except OSError**锛氱鐩樻弧鎴栨潈闄愰棶棰樹笉鍐嶈鎻掍欢鍒濆鍖栧穿
- **`_is_sensitive` 鏀圭敤鍗曡瘝杈圭晫姝ｅ垯**锛氫笉鍐嶈鎶?author/keyboard/secretary/tokenize/credentials 褰撴晱鎰熻瘝
- **鍙嶉绐楀彛鎸?umo 闅旂**锛氬缇?澶氱敤鎴峰満鏅笅鍙嶉涓嶅啀涓插彴
- **`_initiate_self_directed_research(force=True)` 涔熷皧閲?autonomy_enabled 鎬诲紑鍏?*锛氱敤鎴蜂富鏉冧紭鍏?
- **`_maintain_capabilities_health` 閲嶅啓**锛氬悎骞剁浉浼艰兘鍔涙椂 usage_count 涓嶅啀涓㈡洿鏂帮紱浠呴檷鏉冧篃浼氭寔涔呭寲
- **`/anima_capabilities` 鏀寔鍒嗛〉**锛氶伩鍏?QQ 鍗忚绔崟鏉¤浆鍙戞秷鎭秴闀垮鑷村彂閫佸け璐?

### v0.6 鏂板鍔熻兘锛堟牳蹇冿級
- **涓汉鑳藉姏绯荤粺锛圥ersonal Capabilities锛?*锛氳鑹茬幇鍦ㄥ彲浠ャ€岃嚜宸卞浼?+ 鑷繁鍒涢€?+ 鑷繁淇濆瓨 + 鑷繁淇銆嶅伐鍏峰拰鏂规硶
  - 鏁版嵁鏂囦欢 `personal_capabilities.json` + `capabilities_diary.md`
  - 姣忔鑷富鐮旂┒鎴愬姛鍚庯紝LLM 甯鑹叉妸鎴愭灉缁撴瀯鍖栨垚銆屼釜浜哄伐鍏峰崱銆嶏紙鍚?description / how_to_use / parameters_schema / executable_snippet / should_register_as_tool锛?
  - 杩欎簺宸ュ叿浠ラ珮浼樺厛绾ф敞鍏ュ埌瀵硅瘽涓婁笅鏂?
- **鑷富鐮旂┒ 鈫?鑳藉姏鍒涢€犻棴鐜?*锛歚_initiate_self_directed_research`锛堝唴閮ㄩ┍鍔級+ `_danger_autonomous_web`锛堝閮ㄨЕ鍙戯級鍙岃矾寰?
- **鑷垜淇鏈哄埗锛堢粨鏋勫寲 JSON 瑙ｆ瀽鐗堬級**锛氫娇鐢ㄨ兘鍔涘悗 LLM 鐢ㄧ粨鏋勫寲 JSON 璇勪环鎴愬姛/澶辫触 + 鍙嶆€?+ 鏄惁闇€瑕侀噸鍐欒兘鍔涘崱锛屽彲鐪熸淇 `description` / `how_to_use`
- **鐪熷疄 LLM 宸ュ叿璋冪敤鎺ラ€?tool_learning**锛氭墍鏈夐潪涓汉鑳藉姏鐨勫伐鍏疯皟鐢ㄤ篃浼氳繘 `_record_tool_usage`锛岃"宸ュ叿鑷涔?瀵?Sylanne / 鍚勭被 MCP 宸ュ叿閮借捣浣滅敤
- **WebUI 缂栬緫鍣?30s 鍚庡彴杞鍚屾**锛氱紪杈戝櫒淇濆瓨鍚庝笉闇€瑕佺瓑涓嬫潯娑堟伅锛屾渶澶?30s 鑷姩鍐欏叆 self_notes.md
- **`code_execution_safety_level` 涓夋。鐪熸鍒嗗寲**锛歴trict锛堟棤 import锛? balanced锛坖son/re/math/datetime锛? permissive锛堝啀鍔?hashlib/itertools/collections/string/statistics锛?
- **`capability_system_enabled` 鐪熺敓鏁?*锛歞ispatcher 娉ㄥ唽銆佽兘鍔涘垱寤恒€佽兘鍔涙敞鍏ヤ笁澶勫叏閮ㄩ棬鎺?
- **`dynamic_tool_registration_enabled` + `default_register_as_independent_tool` 鐪熺敓鏁?*锛氳兘鍔涘悎鎴?prompt 鐜板湪璁?LLM 杈撳嚭 `should_register_as_tool` 瀛楁锛岀疆淇″害 鈮?.65 + 鏍囪 true 鎵嶄細鐪熸敞鍐屾垚鐙珛 LLM 宸ュ叿
- 鏂版寚浠?`/anima_capabilities`銆乣/anima_autonomy`銆乣/anima_export_capabilities`銆乣/anima_core`

### 娓呯悊
- 鍒犻櫎杩囨椂鐨?`autonomous_web_tools` 閰嶇疆锛坴0.3.6 璧峰氨娌＄敤浜嗭級
- 鍒犻櫎 README 涓?闇€閰嶇疆 fetch/search MCP"杩囨椂鎻忚堪
- 鍒犻櫎浠撳簱涓仐鐣欑殑 schema 鍘嗗彶澶囦唤涓庤皟璇曡剼鏈?

## v0.5.0 - Phase 3 + Phase 5: 浜烘牸鍚戦噺 / 璁板繂鏌撹壊 / 璺ㄥ叧绯讳紶鎾?+ 绐佸彉姹犱笌杩為攣鍙嶅簲

### 鏂板鏈哄埗锛圥hase 3锛?

**浜烘牸鍚戦噺绯荤粺**
- 5 缁村疄鏃跺悜閲忥細琛ㄨ揪娆?/ 鏁忔劅搴?/ 杈圭晫閫氶€?/ 绉╁簭鎰?/ 鍏崇郴寮曞姏
- 瀛樺偍浜?`anima_state.json` 鐨?`personality_vector` 瀛楁
- 姣忔娌夋穩鎴愬姛鍚庢牴鎹嫭鐧藉唴瀹圭敤 EMA锛埼?0.12锛夌紦鎱㈠井璋?
- 鑷姩娉ㄥ叆 `on_llm_request` 涓婁笅鏂囷紝璁╀富妯″瀷鎰熺煡褰撳墠浜烘牸鍊惧悜

**璁板繂鎯呯华鏌撹壊**
- RAG 妫€绱㈠悗瀵硅繑鍥炵殑璁板繂杩涜 valence 浼扮畻锛堟俯鏆栧叧閿瘝 vs 鍐茬獊鍏抽敭璇嶏級
- 褰撳墠鎯呯华 >0.55 鏃朵紭鍏堣繑鍥炴俯鏆栬蹇嗭紱浣庢儏缁椂浼樺厛杩斿洖鍐茬獊璁板繂
- 璁╄鑹插湪涓嶅悓鎯呯华鐘舵€佷笅銆屾兂璧枫€嶄笉鍚屾€ц川鐨勮繃鍘?

**璺ㄥ叧绯讳紶鎾?*
- 缁存姢 per-user 浣庢儏缁繛缁鏁帮紙<0.35 杩炵画 鈮? 娆¤Е鍙戯級
- 璇诲彇 worldview.social_graph锛屾壘鍒颁笌浣庢儏缁敤鎴峰叧绯绘弿杩扮浉浼肩殑鍏朵粬鐢ㄦ埛
- 瀵圭浉浼肩敤鎴风殑浼ょ棔鏁忔劅搴﹁繘琛?+0.04 寰皟锛坮ejection / abandonment / trust_breach 绛夛級
- 浼犳挱鍘嗗彶璁板綍鍦?state 鐨?`cross_propagations`

### 鏂板鏈哄埗锛圥hase 5锛?

**danger_core_mutation 绐佸彉姹?*
- 5 绉嶇獊鍙樼被鍨嬫睜锛氫俊蹇电獊鍙?/ 鍏崇郴閲嶅畾涔?/ 鏂扮蹇?/ 鏂版墽蹇?/ 浜烘牸璺冭縼
- 姣忔瑙﹀彂鍓嶈 LLM 鏍规嵁褰撳墠浜烘牸鍚戦噺 + 鏈€杩戠嫭鐧介€夋嫨鏈€銆岃嚜鐒躲€嶇殑绫诲瀷
- 閽堝涓嶅悓绫诲瀷鐢熸垚涓嶅悓渚ч噸鐐圭殑 persona_core 淇敼
- 绐佸彉鍚庨澶栧壇浣滅敤锛?
  - 浜烘牸璺冭縼锛氬搴旂淮搴﹀仛 卤0.22~0.32 鐨勮穬杩?
  - 鏂版墽蹇碉細鑷姩杞寲涓洪珮寮哄害娆叉湜锛堣嫢娆叉湜绯荤粺寮€鍚級

**杩為攣鍙嶅簲**
- 绐佸彉鎴愬姛鍚庣珛鍗?`force=True` 瑙﹀彂涓栫晫瑙傛洿鏂帮紙鍏崇郴鍙兘琚噸瀹氫箟锛?
- 鑻ュ弽鍒嶅紑鍚紝寮傛瑙﹀彂涓€娆?`_rumination_task` 璁╄鑹叉秷鍖栫獊鍙?
- 鎵€鏈夌獊鍙樻案涔呰褰曞湪 `anima_state.json` 鐨?`mutation_history`锛堟渶澶?100 鏉★級
- 48h 鍐呯殑鏈€杩戠獊鍙樹細鑷姩娉ㄥ叆瀵硅瘽涓婁笅鏂?

### 鍏朵粬
- 鎵╁睍 `_save_state` / 鐘舵€佸姞杞芥敮鎸佹柊瀛楁
- 鏂板澶氬杈呭姪鏂规硶锛歚_get_personality_vector`銆乣_rerank_memories_by_emotion`銆乣_propagate_cross_relation_scar`銆乣_record_mutation` 绛?
- 鎵€鏈夋柊鏈哄埗榛樿鍏抽棴鎴栭浂渚靛叆锛堜汉鏍煎悜閲忔€绘槸杩愯浣嗗奖鍝嶆瀬杞伙級

## v0.4.2 - Phase 4: 鍘婚櫎鏋烽攣

### 鏀瑰姩
- **persona_core.yaml 榛樿鍐呭閲嶅啓** 鈥?鍘绘帀"涓嶆妸鐢ㄦ埛褰撶噧鏂?绛夊閮ㄥ己鍔犺鍒欙紝鏀逛负"鎴戠殑琛屼负杈圭晫鐢辨垜鑷韩鐨勭粡鍘嗗拰婕斿寲鍐冲畾"
- **stance_propagation 闂ㄦ闄嶄綆** 鈥?浠?intensity>0.8 闄嶅埌 >0.5锛屽幓鎺?source=="self" 闄愬埗锛屼换浣曢珮寮哄害娆叉湜閮借兘瑙﹀彂涓诲姩鍙戣█
- **鍙嶅垗鈫掑帇鎶戣瘽棰樿浆鍖?* 鈥?鍙嶅垗鐙櫧涓寘鍚?鎯?娌¤/蹇?鎲?涓嶆暍"绛変俊鍙锋椂锛岃嚜鍔ㄨ浆鍏ュ帇鎶戣瘽棰樼郴缁?

### 璁捐鍘熷垯
- 瑙掕壊鐨勮竟鐣岀敱鑷韩缁忓巻鍐冲畾锛屼笉鐢卞紑鍙戣€呯‖缂栫爜
- 姣忎釜瀛愮郴缁熺殑杈撳嚭閮芥槸鍙︿竴涓瓙绯荤粺鐨勮緭鍏?

## v0.4.1 - Phase 2: 鍘嬫姂璇濋 / 浼ょ棔缁村害 / 鍙嶉闂幆

### 鏂板鏈哄埗

**鍘嬫姂璇濋绯荤粺**
- 瑙掕壊鎯宠浣嗘病璇寸殑璇濅細绉疮鍘嬪姏锛堟瘡灏忔椂 +0.05锛?
- 鍘嬪姏瓒呰繃 0.8 鏃舵敞鍏ュ埌瀵硅瘽涓婁笅鏂囷細"浣犱竴鐩存兂璇翠絾娌¤鍑哄彛鐨勪簨"
- 瑙掕壊璇村嚭鏉ュ悗鍘嬪姏閲婃斁锛岃瘽棰樻爣璁颁负 resolved
- 鏉ユ簮锛氳蹇界暐鐨勫彂瑷€銆佹湭鎵ц鐨勬鏈涖€佸弽鍒嶄腑鐨勬湭琛ㄨ揪鎯虫硶

**浼ょ棔缁村害**
- 5 涓淮搴︼細abandonment / identity_denial / trust_breach / rejection / being_replaced
- 姣忔鍙椾激 sensitivity +0.2锛堜笂闄?3.0锛?
- 鎯呯华璇勫垎涔樹互 sensitivity 绯绘暟锛堜激鐥曡秺娣憋紝鍚岀被浜嬩欢鎯呯华鍙嶅簲瓒婂己锛?
- 瓒呰繃 7 澶╂湭瑙﹀彂鐨勪激鐥曠紦鎱㈡剤鍚堬紙sensitivity -0.1/鍛級
- 鏋侀珮鎯呯华锛?0.9锛夎嚜鍔ㄥ湪瀵瑰簲缁村害浜х敓鏂颁激鐥?

**鍙嶉闂幆**
- 瑙掕壊姣忔鍙戣█鍚庡惎鍔?5 鍒嗛挓瑙傚療绐楀彛
- 鐢ㄦ埛鍥炲簲鍐呭 鈫?accepted锛堝寮鸿璇濋鏉冮噸锛?
- 鐢ㄦ埛璇翠笉鐩稿叧鐨勮瘽 鈫?ignored锛堣浆鍏ュ帇鎶戣瘽棰橈級
- 鐢ㄦ埛鏄庣‘鍚﹀畾 鈫?rejected锛堜骇鐢?rejection 浼ょ棔锛?

### 鏀硅繘
- 娌夋穩娴佺▼寮€澶磋嚜鍔ㄦ洿鏂板帇鎶戣瘽棰樺帇鍔涘拰浼ょ棔琛板噺
- 鎯呯华璇勫垎琚激鐥曠淮搴︽斁澶у悗璁板綍鍒版棩蹇?

## v0.4.0 - Phase 1: 鍩虹闂幆淇

- 鐘舵€佸叏闈㈡寔涔呭寲锛坅nima_state.json锛?
- 鐭涚浘鍙嶅摵琛屼负锛堟敞鍏ュ埌瀵硅瘽涓婁笅鏂囷級
- 鎯呯华璇勫垎娉ㄥ叆瀵硅瘽锛堜富妯″瀷鎰熺煡鎯呯华寮哄害锛?
- 鍙嶅垗浜х敓娆叉湜锛堢绾垮弽鎬濊Е鍙戞柊鐨勮鍔ㄦ剰鍥撅級
- 鐙櫧鍘诲鏌ワ紙鍙鏌ョ┖鍐呭锛?
- 娆叉湜闂ㄦ闄嶄綆锛?.5 鈫?0.3锛?

## v0.3.6 - 鑷富缃戠粶琛屽姩閲嶅啓

- autonomous_web 鏀圭敤 aiohttp + Bing 鎼滅储
- 绉婚櫎 MCP 宸ュ叿渚濊禆
- 鏂板 _fetch_url 鏂规硶

## v0.3.5 - 楂樺嵄鍔熻兘瀹夊叏淇

- stance_propagation 鏀圭敤 llm_generate
- autonomous_web 鏀圭敤 fetch 鐧藉悕鍗?
- ToolSet 绌烘鏌ユ敼鐢?.empty()

## v0.3.4 - 閫昏緫鑷淇

- 绂荤嚎鍙嶅垗绉婚櫎 umo 鍓嶇疆妫€鏌?
- 韬唤鍗辨満淇澶у皬鍐欏尮閰?

## v0.3.3 - 瀹屽杽 core_mutation

- 鍒濆鍖?persona_core.yaml
- on_llm_request 娉ㄥ叆 persona_core
- 瀹夊叏妫€鏌ワ細鐢ㄦ埛涓绘潈涓嶅彲鍒犻櫎
- /anima_core 鎸囦护

## v0.3.1 - 鏁忔劅鍐呭杩囨护鍔犲浐

- 鏂板 _is_sensitive 鏂规硶
- 鍏ㄩ摼璺繃婊わ紙self_notes/evolution_log/鍚戦噺妫€绱?鍙戣█/鎼滅储缁撴灉锛?

## v0.3.0 - 绗笁鐗堝姛鑳藉畬鏁?

- 鐭涚浘妫€娴?/ 绂荤嚎鍙嶅垗 / 婧簮鏌ヨ
- 楂樺嵄鍔熻兘灞傦紙8 涓紑鍏筹級
- 宸ュ叿鑷涔?
- 澶氭ā鍨嬫敮鎸侊紙internal_provider_id / worldview_provider_id锛?

## v0.2.x - 绗簩鐗?

- 娆叉湜绯荤粺 / 涓栫晫瑙傜郴缁?/ 鏃堕棿鎰?/ 鑷劧閬楀繕
- WebUI 缂栬緫鍣?/ 鎷掔粷璇繃婊?/ 瀛樺偍闄愭祦
- Sylanne 鐘舵€佽鍙?

## v0.1.0 - 鍒濈増

- 鎯呯华瑙﹀彂娌夋穩 / self_notes 娉ㄥ叆 / 鍚戦噺璁板繂
- 婕斿寲鏃ュ織 / 鑷姩鍘嬬缉

