import os
import sys

from strands import Agent
from strands.models.openai import OpenAIModel

from ghost_tool import find_ghost_copies

model = OpenAIModel(
    client_args={"base_url": f"https://bedrock-mantle.{os.environ.get('AWS_REGION', 'us-east-1')}.api.aws/v1",
                 "api_key": os.environ["AWS_BEARER_TOKEN_BEDROCK"]},
    model_id="qwen.qwen3-235b-a22b-2507",
)
agent = Agent(model=model, tools=[find_ghost_copies])
email, bucket, prefix = sys.argv[1], sys.argv[2], (sys.argv[3:] or ["demo/"])[0]
agent(f"Did the deletion of {email} really remove them from s3://{bucket}/{prefix}? List every surviving copy.")
