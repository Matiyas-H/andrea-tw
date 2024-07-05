# server.py
import json
import os
import uvicorn
from fastapi import FastAPI, WebSocket, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from twilio.rest import Client
from bot import run_bot

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


from pydantic import BaseModel

class CallRequest(BaseModel):
    to_number: str

# Twilio client setup
account_sid = os.environ['TWILIO_ACCOUNT_SID']
auth_token = os.environ['TWILIO_AUTH_TOKEN']
client = Client(account_sid, auth_token)

@app.get("/")
async def get_call_page():
    with open("static/index.html", "r") as file:
        content = file.read()
    return HTMLResponse(content=content)

@app.post("/make_call")
async def make_call(call_request: CallRequest):
    print(f"Received request to call: {call_request.to_number}")
    try:
        call = client.calls.create(
            url='https://andrea-tw.onrender.com/start_call',
            to=call_request.to_number,
            from_=os.environ['TWILIO_PHONE_NUMBER']
        )
        print(f"Call initiated with SID: {call.sid}")
        return {"message": "Call initiated", "call_sid": call.sid}
    except Exception as e:
        print(f"Error initiating call: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
    

@app.post('/start_call')
async def start_call():
    print("POST TwiML")
    return HTMLResponse(content=open("templates/streams.xml").read(), media_type="application/xml")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    start_data = websocket.iter_text()
 
    first_item = await start_data.__anext__()
    try:
        call_data = json.loads(await start_data.__anext__())
    except StopAsyncIteration:
        print("No more data in the async generator")
        return

    print(call_data, flush=True)
    stream_sid = call_data['start']['streamSid']
    print("WebSocket connection accepted")
    await run_bot(websocket, stream_sid)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    uvicorn.run(app, host="0.0.0.0", port=port)