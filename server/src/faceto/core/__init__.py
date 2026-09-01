"""core/ 框架层 —— 设计 §3.2：不含任何业务逻辑。

依赖铁律（§3.3）：
1. core 不准 import 任何 domains/*；
2. domains 之间只准 import 对方 service 接口，不准 import repo/model；
3. 跨域写操作走领域事件（生产为 Kafka），本实现通过 events 总线模拟。
"""
