import json
import os
import uvicorn
from fastapi import FastAPI, WebSocket, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
from loguru import logger
from bot import run_bot

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the static directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Twilio client setup
account_sid = os.environ['TWILIO_ACCOUNT_SID']
auth_token = os.environ['TWILIO_AUTH_TOKEN']
twilio_client = Client(account_sid, auth_token)

@app.get("/")
async def root():
    with open("static/index.html", "r") as file:
        content = file.read()
    return HTMLResponse(content=content)

@app.post('/start_call')
async def start_call():
    print("POST TwiML")
    return HTMLResponse(content=open("templates/streams.xml").read(), media_type="application/xml")

@app.post('/initiate_outbound_call')
async def initiate_outbound_call(background_tasks: BackgroundTasks, to_number: str):
    def make_call():
        call = twilio_client.calls.create(
            url=f"https://{os.environ.get('RENDER_EXTERNAL_URL')}/outbound_call_handler",
            to=to_number,
            from_=os.environ['TWILIO_PHONE_NUMBER']
        )
        print(f"Call SID: {call.sid}")

    background_tasks.add_task(make_call)
    return {"message": "Outbound call initiated"}

@app.post('/outbound_call_handler')
async def outbound_call_handler():
    response = VoiceResponse()
    response.say("Hello, this is an AI assistant calling. Please wait while I connect you.")
    response.connect().stream(url=f"wss://{os.environ.get('RENDER_EXTERNAL_URL')}/ws")
    logger.info(f"Outbound call TwiML: {response}")
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    logger.info("WebSocket connection attempt")
    await websocket.accept()
    logger.info("WebSocket connection accepted")
    
    try:
        start_data = websocket.iter_text()
        initial_message = await start_data.__anext__()
        logger.info(f"Initial WebSocket message: {initial_message}")
        
        call_data = json.loads(await start_data.__anext__())
        logger.info(f"Call data: {call_data}")
        
        stream_sid = call_data['start']['streamSid']
        logger.info(f"Stream SID: {stream_sid}")
        
        # Determine if this is an outbound call
        is_outbound = call_data.get('start', {}).get('outbound') == 'true'
        logger.info(f"Is outbound call: {is_outbound}")
        
        await run_bot(websocket, stream_sid, is_outbound)
    except Exception as e:
        logger.error(f"Error in websocket_endpoint: {str(e)}")
    finally:
        logger.info("WebSocket connection closed")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    uvicorn.run(app, host="0.0.0.0", port=port)