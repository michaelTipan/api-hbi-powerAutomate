
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
    
    endpoint = f"sites/{site_id}/drives/{drive_id}/root:/INFORMACION CREDITOS-CLIENTES/CONSTRUVID:/children"
    try:
        children = await client.get(endpoint)
        for item in children.get("value", []):
            if "218" in item.get("name", ""):
                print(f"Found folder: {item.get('name')}")
                folder_endpoint = f"sites/{site_id}/drives/{drive_id}/items/{item.get('id')}/children"
                pdfs = await client.get(folder_endpoint)
                for pdf in pdfs.get("value", []):
                    name = pdf.get("name", "")
                    c_time = pdf.get("fileSystemInfo", {}).get("createdDateTime")
                    m_time = pdf.get("fileSystemInfo", {}).get("lastModifiedDateTime")
                    print(f"  File: {name} | created: {c_time} | modified: {m_time}")
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(main())

