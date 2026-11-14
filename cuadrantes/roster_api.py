"""HTTP adapter for K124 CP-SAT roster solver.

Run from repository root:
  pip install -r cuadrantes/api-requirements.txt
  uvicorn cuadrantes.roster_api:app --host 0.0.0.0 --port 8000
"""
from datetime import date
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from cuadrantes.roster_engine import solve_roster

app = FastAPI(title="K124 Roster Wizard API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://calvovizcaino-star.github.io"],
    allow_credentials=False,
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)

class Vacation(BaseModel):
    person: str
    from_: str = Field(alias="from")
    to: str

class Request(BaseModel):
    start: date
    days: int = Field(ge=1, le=125)
    vacations: list[Vacation] = Field(default_factory=list)
    fixed: dict[str, dict[str, str]] = Field(default_factory=dict)
    previous_late: dict[str, list[str]] = Field(default_factory=dict)
    time_limit_seconds: int = Field(default=45, ge=1, le=90)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/solve")
def solve(req: Request):
    try:
        return solve_roster(
            start=req.start,
            days=req.days,
            vacations=[v.model_dump(by_alias=True) for v in req.vacations],
            fixed=req.fixed,
            previous_late=req.previous_late,
            time_limit_seconds=req.time_limit_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
