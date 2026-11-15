Good news: the answer is pretty clear-cut for your project. Here's the ranking:

## Tier 1 — Must Use (do these, no debate)

| Service | What you use it for | Setup time | Why it wins |
|---------|-------------------|-----------|------------|
| **Amazon Bedrock** | Your LLM calls (replace OpenAI/Claude API with `boto3` → `bedrock-runtime` → `converse()`) | ~10 min | This is *the* AWS-native way to call an LLM. Judges see "Bedrock" and think "they used AWS properly." Use **Claude Sonnet** or **Llama 3** (smaller models, not the "big big" ones you can't access). One API call change from what you'd do with OpenAI. |
| **Amazon S3** | Store your portfolio JSON, pre-fetched FRED/yfinance data, and each agent's output as a file | ~5 min | Free tier (5 GB). Shows you're thinking in an architecture, not just a script. "Agents read from S3, write results back to S3" is a one-liner in your tech doc. |
| **Amazon EC2** (t3.small) | Deploy your Streamlit app | ~15 min | SSH in, `pip install`, `streamlit run app.py`. That's it. You get a public URL (`http://ec2-ip:8501`). **App Runner is dead** (sunset April 2026) and never supported WebSockets anyway, so EC2 is the only simple option. |

## Tier 2 — High ROI Differentiators (do if you have 1–2h to spare)

| Service | What you use it for | Why it wins |
|---------|-------------------|------------|
| **Bedrock AgentCore** | Deploy *one* of your agents (e.g., the Macro Scout) as an AgentCore Runtime via their CLI (`npm install -g @aws/agentcore`) | This is AWS's **native agent platform** (GA October 2026). If your tech doc says "agents run on CrewAI locally, Macro Scout is deployed as an AgentCore Runtime," you've shown you understand the full AWS agent stack. It's a big "wow" for judges who know AWS. **Risk:** it's new, docs are still settling. Budget 1–2h max. If it fights you, drop it and just use CrewAI. |
| **IAM** (instance profile + roles) | EC2 gets an instance profile with `bedrock:InvokeModel` + `s3:GetObject/PutObject`. No hardcoded keys. | Shows you're not a script kiddo. 10 min in the console. Mention it in your tech doc. |
| **CloudWatch** (basic logging) | Each agent logs its reasoning to CloudWatch Logs. One `boto3` call per agent step. | "We can audit every agent decision" is a great one-liner for institutional investors. 5 min to add. |

## Tier 3 — Nice to Have (only if you're ahead of schedule)

| Service | Use | Verdict |
|---------|-----|---------|
| **Amazon SNS** | "Agent finished → send email/SMS with recommendation" | Cool story, but not essential. Skip unless you have 2h+ of buffer. |
| **CloudFront + ALB** | HTTPS in front of EC2 | Nice to have, but `http://ip:8501` is fine for a 48h demo. Skip. |
| **AWS Glue / Athena** | Query data in S3 with SQL | Overkill. You're using pandas/yfinance, not a data lake. |

## Tier 4 — Omit (time sinks, zero ROI for this project)

| Service | Why to skip |
|---------|------------|
| **SageMaker** | For training/fine-tuning models. You're not training anything. |
| **EKS / ECS Fargate** | Kubernetes / containers. Way overkill for a single Streamlit app. |
| **DynamoDB / RDS** | You don't need a database. JSON files in S3 + `st.session_state` is fine. |
| **Lambda** | Cold starts. Can't run Streamlit (no persistent WebSocket). |
| **Step Functions** | Workflow orchestration — CrewAI already does this. |
| **Cognito** | Auth. One demo, one user. Not needed. |
| **EMR / Redshift** | Big data. Irrelevant. |
| **Secrets Manager** | IAM + env vars are fine for 48h. |

## The "AWS Story" for Your Tech Doc & Demo

Frame it as:

> "Our system runs on a fully AWS-native stack: **Bedrock** powers all LLM reasoning (Claude Sonnet), **AgentCore** hosts our Macro Scout agent as a managed runtime, **S3** serves as the data layer for market inputs and agent outputs, **CloudWatch** provides full audit logging of every agent decision, and the application is deployed on **EC2** with proper **IAM** role-based access."

That's 6 AWS services named in one sentence. It sounds like a real product architecture, not a hackathon project. And it's all true if you do Tier 1 + Tier 2.

## Practical Note on Bedrock

The "big big models" you can't access are probably the frontier-tier ones (Claude Opus, largest Llama). You **will** have access to:
- **Claude Sonnet** (best quality/speed ratio for your agents)
- **Claude Haiku** (fastest, cheapest — use for simple classification tasks)
- **Llama 3 / 3.1** (open-weight, fast)
- **Amazon Nova** (AWS's own model)

Use **Sonnet** for your Portfolio PM agent (the one that synthesizes and reasons) and **Haiku** for the Macro Scout (simple regime classification). This also shows you understand model routing by complexity — another point for the tech doc.

