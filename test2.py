
import asyncio
from dotenv import load_dotenv

load_dotenv(".env.active")
from app.adapters.secondary.ms_graph_client import MsGraphClient
from app.application.use_cases.payment_validation_generate import resolve_sharepoint_path

async def main():
    client = MsGraphClient()
    clients_info = await resolve_sharepoint_path(client, "HBI-Capital", "Documentos", "INFORMACION CREDITOS-CLIENTES")
    site_id = clients_info["site_id"]
    drive_id = clients_info["drive_id"]
    
    endpoint = f"sites/{site_id}/drives/{drive_id}/root:/INFORMACION CREDITOS-CLIENTES:/children"
    children = await client.get_json(endpoint)
    for item in children.get("value", []):
        name = item.get("name", "")
        if "TRANSPORTE" in name.upper():
            print(f"FOUND MATCHING FOLDER: [{name}]")

asyncio.run(main())

