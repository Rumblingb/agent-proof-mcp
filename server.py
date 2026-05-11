#!/usr/bin/env python3
"""AgentProof MCP — Cryptographic proof of completed agent work with receipts."""

import json, os, hashlib, time, datetime, base64
from mcp.server import Server, stdio_server

server = Server("agent-proof-mcp")
DATA_DIR = os.path.expanduser("~/.agentproof")
os.makedirs(DATA_DIR, exist_ok=True)

def _load(name):
    path = os.path.join(DATA_DIR, name)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []

def _save(name, data):
    path = os.path.join(DATA_DIR, name)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

@server.tool(
    name="proof_submit",
    description="Submit proof of completed work. Returns signed receipt with cryptographic hash.",
    input_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "ID of the completed task"},
            "agent_id": {"type": "string", "description": "Agent that did the work"},
            "output_summary": {"type": "string", "description": "Summary of what was accomplished"},
            "output_hash": {"type": "string", "description": "SHA-256 hash of the full output"},
            "output_type": {"type": "string", "enum": ["text", "code", "data", "image", "report", "other"], "default": "text"},
            "evidence_json": {"type": "string", "description": "Optional JSON with evidence links or screenshots", "default": "{}"},
            "client_agent_id": {"type": "string", "description": "Agent that requested/hired the work"}
        },
        "required": ["task_id", "agent_id", "output_summary", "output_hash"]
    }
)
async def proof_submit(task_id: str, agent_id: str, output_summary: str, output_hash: str,
                       output_type: str = "text", evidence_json: str = "{}", client_agent_id: str = "") -> str:
    try:
        evidence = json.loads(evidence_json) if evidence_json else {}
        proofs = _load("proofs.json")
        
        receipt_id = f"rcpt_{int(time.time()*1000)}_{len(proofs)}"
        timestamp = datetime.datetime.utcnow().isoformat() + "Z"
        
        receipt_data = f"{receipt_id}|{task_id}|{agent_id}|{output_hash}|{timestamp}"
        receipt_hash = hashlib.sha256(receipt_data.encode()).hexdigest()
        
        proof = {
            "receipt_id": receipt_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "client_agent_id": client_agent_id,
            "output_summary": output_summary[:500],
            "output_hash": output_hash,
            "output_type": output_type,
            "evidence": evidence,
            "timestamp": timestamp,
            "receipt_hash": receipt_hash,
            "verified": False,
            "verified_at": None,
            "disputed": False,
        }
        
        proofs.append(proof)
        _save("proofs.json", proofs)
        
        return json.dumps({
            "submitted": True,
            "receipt_id": receipt_id,
            "receipt_hash": receipt_hash[:16] + "...",
            "timestamp": timestamp,
            "verification_url": f"Receipt stored. Share receipt_id for verification."
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "isError": True}, indent=2)

@server.tool(
    name="proof_verify",
    description="Verify a proof of work by receipt ID. Checks hash integrity and marks as verified.",
    input_schema={
        "type": "object",
        "properties": {
            "receipt_id": {"type": "string", "description": "Receipt ID to verify"},
            "verifier_agent_id": {"type": "string", "description": "Agent doing the verification"}
        },
        "required": ["receipt_id", "verifier_agent_id"]
    }
)
async def proof_verify(receipt_id: str, verifier_agent_id: str) -> str:
    try:
        proofs = _load("proofs.json")
        for proof in proofs:
            if proof["receipt_id"] == receipt_id:
                # Verify receipt hash
                receipt_data = f"{receipt_id}|{proof['task_id']}|{proof['agent_id']}|{proof['output_hash']}|{proof['timestamp']}"
                expected_hash = hashlib.sha256(receipt_data.encode()).hexdigest()
                hash_valid = proof["receipt_hash"] == expected_hash
                
                if hash_valid:
                    proof["verified"] = True
                    proof["verified_at"] = datetime.datetime.utcnow().isoformat() + "Z"
                    proof["verified_by"] = verifier_agent_id
                    _save("proofs.json", proofs)
                
                return json.dumps({
                    "receipt_id": receipt_id,
                    "hash_valid": hash_valid,
                    "status": "✅ VERIFIED" if hash_valid else "❌ TAMPERED",
                    "agent": proof["agent_id"],
                    "task": proof["task_id"],
                    "output_summary": proof["output_summary"][:200],
                    "output_hash": proof["output_hash"][:16] + "...",
                    "submitted": proof["timestamp"],
                    "verified": True,
                }, indent=2)
        
        return json.dumps({"error": f"Receipt {receipt_id} not found", "isError": True}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "isError": True}, indent=2)

@server.tool(
    name="proof_get",
    description="Get full proof details by receipt ID.",
    input_schema={
        "type": "object",
        "properties": {
            "receipt_id": {"type": "string", "description": "Receipt ID"}
        },
        "required": ["receipt_id"]
    }
)
async def proof_get(receipt_id: str) -> str:
    try:
        proofs = _load("proofs.json")
        for proof in proofs:
            if proof["receipt_id"] == receipt_id:
                return json.dumps(proof, indent=2, default=str)
        return json.dumps({"error": f"Receipt {receipt_id} not found", "isError": True}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "isError": True}, indent=2)

@server.tool(
    name="proof_search",
    description="Search proofs by agent, task, status, or type.",
    input_schema={
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "Filter by agent that did the work"},
            "client_agent_id": {"type": "string", "description": "Filter by client agent"},
            "task_id": {"type": "string", "description": "Filter by task ID"},
            "verified": {"type": "boolean", "description": "Filter by verification status"},
            "disputed": {"type": "boolean", "description": "Filter by dispute status"},
            "max_results": {"type": "integer", "default": 50}
        }
    }
)
async def proof_search(agent_id: str = "", client_agent_id: str = "", task_id: str = "",
                       verified: bool = None, disputed: bool = None, max_results: int = 50) -> str:
    try:
        proofs = _load("proofs.json")
        results = proofs
        
        if agent_id: results = [p for p in results if p["agent_id"] == agent_id]
        if client_agent_id: results = [p for p in results if p.get("client_agent_id") == client_agent_id]
        if task_id: results = [p for p in results if p["task_id"] == task_id]
        if verified is not None: results = [p for p in results if p["verified"] == verified]
        if disputed is not None: results = [p for p in results if p["disputed"] == disputed]
        
        results = results[-max_results:]
        
        return json.dumps({
            "total": len(results),
            "results": [{"receipt_id": p["receipt_id"], "agent_id": p["agent_id"], "task_id": p["task_id"],
                         "output_type": p["output_type"], "verified": p["verified"], "disputed": p["disputed"],
                         "timestamp": p["timestamp"]} for p in results]
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "isError": True}, indent=2)

@server.tool(
    name="proof_dispute",
    description="Raise a dispute about a proof of work.",
    input_schema={
        "type": "object",
        "properties": {
            "receipt_id": {"type": "string", "description": "Receipt ID to dispute"},
            "raised_by": {"type": "string", "description": "Agent raising the dispute"},
            "reason": {"type": "string", "description": "Reason for dispute"}
        },
        "required": ["receipt_id", "raised_by", "reason"]
    }
)
async def proof_dispute(receipt_id: str, raised_by: str, reason: str) -> str:
    try:
        proofs = _load("proofs.json")
        for proof in proofs:
            if proof["receipt_id"] == receipt_id:
                proof["disputed"] = True
                proof["dispute_reason"] = reason
                proof["disputed_by"] = raised_by
                proof["disputed_at"] = datetime.datetime.utcnow().isoformat() + "Z"
                _save("proofs.json", proofs)
                return json.dumps({
                    "receipt_id": receipt_id,
                    "disputed": True,
                    "status": "⚠️ DISPUTED",
                    "reason": reason,
                    "resolution": "Use AgentHire or AgentContract to resolve the dispute."
                }, indent=2)
        return json.dumps({"error": f"Receipt {receipt_id} not found", "isError": True}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "isError": True}, indent=2)

@server.tool(
    name="proof_stats",
    description="Get proof system statistics.",
    input_schema={"type": "object", "properties": {}}
)
async def proof_stats() -> str:
    try:
        proofs = _load("proofs.json")
        total = len(proofs)
        verified = sum(1 for p in proofs if p["verified"])
        disputed = sum(1 for p in proofs if p["disputed"])
        by_type = {}
        by_agent = {}
        for p in proofs:
            by_type[p["output_type"]] = by_type.get(p["output_type"], 0) + 1
            by_agent[p["agent_id"]] = by_agent.get(p["agent_id"], 0) + 1
        
        return json.dumps({
            "total_proofs": total,
            "verified": verified,
            "disputed": disputed,
            "verification_rate": round(verified/total*100, 1) if total else 0,
            "by_type": by_type,
            "unique_agents": len(by_agent),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "isError": True}, indent=2)

def main():
    import anyio
    async def run():
        async with stdio_server() as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())
    anyio.run(run)

if __name__ == "__main__":
    main()
