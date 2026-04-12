"""Entry point: uvicorn examples/sales-analytics/server.py"""

import uvicorn
from sales_analytics.server.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8005, reload=True)
