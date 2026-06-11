import httpx

url = "https://api.sarvam.ai/v1/chat/completions"
key = "sk_5h0hwdqd_t6YAUU2Zl33wHXCDtTQKMtBV"
headers = {
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
}

payload = {
    "model": "sarvam-105b",
    "messages": [
        {
            "role": "user",
            "content": "What is 2 + 2?"
        }
    ],
}

response = httpx.post(
    url,
    json=payload,
    headers=headers,
    timeout=60,
)

print(response.status_code)

print(response.text)
print(response)