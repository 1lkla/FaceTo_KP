"""domains/ —— 业务域 = 未来微服务边界（§3.2）。

依赖铁律（§3.3）：
1. 域间只 import 对方 service 级函数（本实现即 router.py 内标注为 service 的函数）；
2. 跨域写走事件总线（store.bus，生产 Kafka）；
3. 每个域 router 前缀 = 服务名 = K8s namespace 预留。
"""
