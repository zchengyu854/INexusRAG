flowchart TD
    subgraph Indexing[文档切片与向量化]
        File[PDF / Markdown / TXT] --> Loader[加载与清洗]
        Loader --> Splitter[Markdown-aware 切片<br/>标题 → 段落/列表/代码 → 句子 → 字符兜底]
        Splitter --> Chunk[Chunk<br/>文本 + chunk_index + metadata<br/>heading_path / page]
        Chunk --> Embed[Embedding 模型<br/>每个 Chunk → 向量]
        Chunk --> VectorDB[(PostgreSQL + pgvector)]
        Embed --> VectorDB
    end

    subgraph Query[查询与结果返回]
        Question[用户问题] --> QueryEmbed[Embedding 模型<br/>问题 → query_vector]
        Question --> Terms[jieba 分词<br/>提取关键词]
        QueryEmbed --> VectorSearch[向量检索<br/>cosine similarity]
        Terms --> KeywordSearch[关键词检索<br/>ILIKE + pg_trgm]
        VectorSearch --> RRF[RRF 融合<br/>按 chunk_id 去重并排序]
        KeywordSearch --> RRF
        RRF --> TopK[Top-K 检索结果<br/>text + doc_name + chunk_index<br/>page + score]
        TopK --> Sources[返回 sources]
        TopK --> LLM[LLM 基于检索结果生成答案]
        LLM --> Response[返回 answer + sources<br/>conversation_id + latency_ms]
    end

    VectorDB --> VectorSearch
    VectorDB --> KeywordSearch
