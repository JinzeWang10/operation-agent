"""知识复核台:cases.jsonl 机器抽取的人工复核 + overlay 修订层。

机器抽取只读(cases.jsonl),人工修订独立存 PG(overlay),读取时叠加、机器重跑不丢。
详见 docs / big_data_model/knowledge_pipeline/DEPLOY.md「三点六」。
"""
