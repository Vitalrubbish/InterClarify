# TextTurn过渡句冻结清单

2026-10-27。按已确认修复方案，在生成器实现前交付以下人工编写清单。长度使用旧冻结集内固定Qwen tokenizer实计；train 24条、dev 8条，句式族隔离。这些句子只模拟尚无完整因果答案时的过渡输出，不声称回答了问题，不调用额外模型。

|切分|句式族|文本|token数|
|---|---|---|---|
|train|train-0|Let me work through the details before giving the complete answer.|12|
|train|train-0|Let me separate the main points before explaining them in order.|12|
|train|train-0|Let me check how these parts fit together in this situation.|12|
|train|train-0|Let me consider the conditions that matter for your request.|11|
|train|train-1|I will begin with the central idea and then examine the details.|13|
|train|train-1|I will organize the explanation around the question you have raised.|12|
|train|train-1|I will look at the practical implications as well as the basic idea.|14|
|train|train-1|I will work from the information you have provided so far.|12|
|train|train-2|There are several relevant points to consider before reaching an answer.|12|
|train|train-2|There are a few distinctions that will help organize this explanation.|12|
|train|train-2|There are some useful connections to examine in the information provided.|12|
|train|train-2|There are different aspects of this request that deserve separate attention.|12|
|train|train-3|First, we can identify the main issue and its surrounding context.|13|
|train|train-3|First, we can establish what the question is asking us to explain.|14|
|train|train-3|First, we can consider the available information and the remaining uncertainty.|13|
|train|train-3|First, we can distinguish the general principle from the specific example.|13|
|train|train-4|A useful starting point is to consider the situation as a whole.|13|
|train|train-4|A useful starting point is to identify which details affect the answer.|13|
|train|train-4|A useful starting point is to connect this request with its context.|13|
|train|train-4|A useful starting point is to examine the question one part at a time.|15|
|train|train-5|To address this carefully, I will consider both the context and the details.|15|
|train|train-5|To explain this clearly, I will work through the relevant points in order.|15|
|train|train-5|To respond to your request, I will first identify the key considerations.|14|
|train|train-5|To develop the answer, I will examine how the different pieces relate.|14|
|dev|dev-0|Your question calls for a careful look at the information available.|12|
|dev|dev-0|Your request raises a distinction that deserves a clear explanation.|11|
|dev|dev-1|Before offering an answer, the relevant conditions need some attention.|12|
|dev|dev-1|Before drawing conclusions, the relationship between these points needs clarification.|12|
|dev|dev-2|Working through this question involves connecting the general idea with its context.|13|
|dev|dev-2|Working through the details will help make the reasoning easier to follow.|13|
|dev|dev-3|From the context provided, the next step is to examine the main issue.|15|
|dev|dev-3|From this starting point, the explanation can develop one point at a time.|15|
