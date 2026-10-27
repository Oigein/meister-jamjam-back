from fastapi import FastAPI

app = FastAPI(title="meister-jamjam-back")


@app.get("/")
def root():
    return {"message": "meister-jamjam-back is running"}


@app.get("/health")
def health():
    return {"status": "ok"}
