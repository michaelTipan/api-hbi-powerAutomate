
import asyncio
import os
from dotenv import load_dotenv

load_dotenv(".env.active")
from app.infrastructure.external.graph_client import GraphClient
from app.application.use_cases.payment_validation_generate import resolve_sharepoint_path

async def main():
    client = GraphClient()
    await client.connect()
    
    site_search = os.environ.get("SHAREPOINT_SITE_SEARCH", "HBI-Capital")
    drive_name = os.environ.get("SHAREPOINT_DRIVE_NAME", "Documentos")
    clients_path = os.environ.get("SHAREPOINT_CLIENTS_PATH", "INFORMACION CREDITOS-CLIENTES")
    
    try:
        clients_info = await resolve_sharepoint_path(client, site_search, drive_name, clients_path)
        site_id = clients_info["site_id"]
        drive_id = clients_info["drive_id"]
        
        endpoint = f"sites/{site_id}/drives/{drive_id}/root:/{clients_path}:/children"
        children = await client.get_json(endpoint)
        for item in children.get("value", []):
            name = item.get("name", "")
            if "TRANSPORTE" in name.upper() or "MAQUINARIA" in name.upper():
                print(f"FOUND MATCHING FOLDER: [{name}]")
    finally:
        await client.close()

asyncio.run(main())

