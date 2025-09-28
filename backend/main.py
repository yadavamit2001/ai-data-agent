from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import pandas as pd
import numpy as np
import io
import re
import sqlite3
from typing import Optional, Dict, Any, List
import openai
import os
from datetime import datetime
import json
import plotly.graph_objects as go
import plotly.express as px
from plotly.utils import PlotlyJSONEncoder
from sqlalchemy import create_engine, MetaData, Table, Column, String, Float, Integer, DateTime, text
from sqlalchemy.orm import sessionmaker
import uuid

app = FastAPI(title="AI Data Agent", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database setup (will use Railway PostgreSQL in production)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data_agent.db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
metadata = MetaData()

# OpenAI setup
openai.api_key = os.getenv("OPENAI_API_KEY")

class DataProcessor:
    def __init__(self):
        self.uploaded_files = {}
    
    def clean_column_name(self, col_name):
        """Clean and standardize column names"""
        if pd.isna(col_name) or col_name == '' or str(col_name).startswith('Unnamed'):
            return f"Column_{uuid.uuid4().hex[:6]}"
        
        # Clean the column name
        clean_name = str(col_name).strip()
        clean_name = re.sub(r'[^\w\s]', '', clean_name)
        clean_name = re.sub(r'\s+', '_', clean_name)
        return clean_name[:50]  # Limit length
    
    def detect_data_type(self, series):
        """Intelligently detect data types"""
        # Remove nulls for type detection
        non_null_series = series.dropna()
        if len(non_null_series) == 0:
            return 'TEXT'
        
        # Try numeric first
        try:
            pd.to_numeric(non_null_series)
            if all(float(x).is_integer() for x in non_null_series if pd.notnull(x)):
                return 'INTEGER'
            return 'REAL'
        except:
            pass
        
        # Try datetime
        try:
            pd.to_datetime(non_null_series)
            return 'DATETIME'
        except:
            pass
        
        return 'TEXT'
    
    def process_excel_file(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """Process Excel file and return structured data"""
        try:
            # Read Excel file
            excel_file = pd.ExcelFile(io.BytesIO(file_content))
            
            processed_sheets = {}
            
            for sheet_name in excel_file.sheet_names:
                # Read sheet
                df = pd.read_excel(excel_file, sheet_name=sheet_name)
                
                # Clean column names
                df.columns = [self.clean_column_name(col) for col in df.columns]
                
                # Remove completely empty rows
                df = df.dropna(how='all')
                
                # Basic data cleaning
                for col in df.columns:
                    if df[col].dtype == 'object':
                        # Clean string data
                        df[col] = df[col].astype(str).str.strip()
                        df[col] = df[col].replace(['', 'nan', 'None', 'null'], np.nan)
                
                # Store processed data
                processed_sheets[sheet_name] = {
                    'data': df,
                    'shape': df.shape,
                    'columns': list(df.columns),
                    'dtypes': {col: self.detect_data_type(df[col]) for col in df.columns}
                }
            
            # Generate unique table ID
            table_id = f"table_{uuid.uuid4().hex[:8]}"
            
            # Store in database
            self.store_in_database(processed_sheets, table_id, filename)
            
            return {
                'table_id': table_id,
                'filename': filename,
                'sheets': {name: {
                    'shape': info['shape'],
                    'columns': info['columns'],
                    'dtypes': info['dtypes']
                } for name, info in processed_sheets.items()},
                'upload_time': datetime.now().isoformat()
            }
            
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error processing Excel file: {str(e)}")
    
    def store_in_database(self, sheets_data: Dict, table_id: str, filename: str):
        """Store processed data in database"""
        try:
            for sheet_name, sheet_info in sheets_data.items():
                df = sheet_info['data']
                table_name = f"{table_id}_{sheet_name}".replace(' ', '_').replace('-', '_')
                
                # Create table in database
                df.to_sql(table_name, engine, if_exists='replace', index=False)
                
                # Store metadata
                metadata_table = f"{table_id}_metadata"
                metadata_df = pd.DataFrame([{
                    'table_name': table_name,
                    'sheet_name': sheet_name,
                    'filename': filename,
                    'columns': json.dumps(sheet_info['columns']),
                    'dtypes': json.dumps(sheet_info['dtypes']),
                    'row_count': sheet_info['shape'][0],
                    'col_count': sheet_info['shape'][1],
                    'created_at': datetime.now()
                }])
                
                metadata_df.to_sql(metadata_table, engine, if_exists='append', index=False)
                
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error storing data: {str(e)}")

class AIAgent:
    def __init__(self):
        self.system_prompt = """
        You are an expert data analyst AI that helps users analyze their Excel data through natural language queries.
        
        Given a user's question about their data, you need to:
        1. Understand what they're asking for
        2. Generate appropriate SQL queries to answer their question
        3. Suggest the best visualization type
        4. Provide insights about the results
        
        Available visualization types: bar, line, pie, scatter, table, heatmap
        
        Always respond in JSON format with:
        {
            "sql_query": "SELECT statement",
            "visualization_type": "chart type",
            "explanation": "what this query does",
            "insights": "key insights to look for"
        }
        """
    
    async def process_query(self, question: str, table_info: Dict) -> Dict[str, Any]:
        """Process natural language query and return SQL + visualization suggestions"""
        try:
            # Prepare context about available data
            context = f"""
            Available tables and columns:
            {json.dumps(table_info, indent=2)}
            
            User question: "{question}"
            """
            
            response = await openai.ChatCompletion.acreate(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": context}
                ],
                temperature=0.1
            )
            
            result = json.loads(response.choices[0].message.content)
            return result
            
        except Exception as e:
            # Fallback with basic query generation
            return self.generate_fallback_query(question, table_info)
    
    def generate_fallback_query(self, question: str, table_info: Dict) -> Dict[str, Any]:
        """Generate basic query when AI fails"""
        # Simple keyword-based query generation
        question_lower = question.lower()
        
        # Get first table and columns
        first_table = list(table_info.keys())[0]
        columns = table_info[first_table]['columns']
        
        if any(word in question_lower for word in ['trend', 'time', 'over time']):
            return {
                "sql_query": f"SELECT * FROM {first_table} LIMIT 100",
                "visualization_type": "line",
                "explanation": "Showing data trends over time",
                "insights": "Look for patterns and changes in the data"
            }
        elif any(word in question_lower for word in ['sum', 'total', 'count']):
            return {
                "sql_query": f"SELECT * FROM {first_table} LIMIT 100",
                "visualization_type": "bar",
                "explanation": "Showing aggregated data",
                "insights": "Compare totals across categories"
            }
        else:
            return {
                "sql_query": f"SELECT * FROM {first_table} LIMIT 100",
                "visualization_type": "table",
                "explanation": "Showing raw data overview",
                "insights": "Examine the data structure and values"
            }

# Initialize processors
data_processor = DataProcessor()
ai_agent = AIAgent()

@app.get("/")
async def root():
    return {"message": "AI Data Agent API", "status": "running"}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload and process Excel file"""
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Please upload an Excel file (.xlsx or .xls)")
    
    try:
        content = await file.read()
        result = data_processor.process_excel_file(content, file.filename)
        return JSONResponse(content=result)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query")
async def process_query(request_data: dict):
    """Process natural language query"""
    try:
        table_id = request_data.get('table_id')
        question = request_data.get('question')
        
        if not table_id or not question:
            raise HTTPException(status_code=400, detail="table_id and question are required")
        
        # Get table info from database
        metadata_query = f"SELECT * FROM {table_id}_metadata"
        metadata_df = pd.read_sql(metadata_query, engine)
        
        table_info = {}
        for _, row in metadata_df.iterrows():
            table_info[row['table_name']] = {
                'columns': json.loads(row['columns']),
                'dtypes': json.loads(row['dtypes']),
                'row_count': row['row_count']
            }
        
        # Process query with AI
        ai_response = await ai_agent.process_query(question, table_info)
        
        # Execute SQL query
        try:
            query_result = pd.read_sql(ai_response['sql_query'], engine)
            
            # Generate visualization
            chart_data = generate_visualization(query_result, ai_response['visualization_type'])
            
            return JSONResponse(content={
                'success': True,
                'data': query_result.to_dict('records'),
                'chart': chart_data,
                'explanation': ai_response['explanation'],
                'insights': ai_response['insights'],
                'row_count': len(query_result)
            })
            
        except Exception as sql_error:
            return JSONResponse(content={
                'success': False,
                'error': f"SQL execution error: {str(sql_error)}",
                'fallback_explanation': ai_response['explanation']
            })
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def generate_visualization(df: pd.DataFrame, chart_type: str) -> Dict:
    """Generate chart data based on DataFrame and chart type"""
    try:
        if df.empty:
            return {'type': 'table', 'data': []}
        
        if chart_type == 'bar':
            # Use first two columns for bar chart
            if len(df.columns) >= 2:
                fig = px.bar(df.head(20), x=df.columns[0], y=df.columns[1])
            else:
                fig = px.bar(df.head(20), y=df.columns[0])
            
        elif chart_type == 'line':
            if len(df.columns) >= 2:
                fig = px.line(df.head(50), x=df.columns[0], y=df.columns[1])
            else:
                fig = px.line(df.head(50), y=df.columns[0])
                
        elif chart_type == 'pie':
            if len(df.columns) >= 2:
                # Group by first column, sum second column
                pie_data = df.groupby(df.columns[0])[df.columns[1]].sum().head(10)
                fig = px.pie(values=pie_data.values, names=pie_data.index)
            else:
                value_counts = df[df.columns[0]].value_counts().head(10)
                fig = px.pie(values=value_counts.values, names=value_counts.index)
                
        elif chart_type == 'scatter':
            if len(df.columns) >= 2:
                fig = px.scatter(df.head(100), x=df.columns[0], y=df.columns[1])
            else:
                return {'type': 'table', 'data': df.head(50).to_dict('records')}
                
        else:  # table
            return {'type': 'table', 'data': df.head(100).to_dict('records')}
        
        return {
            'type': chart_type,
            'plotly_json': json.loads(fig.to_json())
        }
        
    except Exception as e:
        # Fallback to table
        return {'type': 'table', 'data': df.head(50).to_dict('records')}

@app.get("/tables/{table_id}/info")
async def get_table_info(table_id: str):
    """Get information about uploaded table"""
    try:
        metadata_query = f"SELECT * FROM {table_id}_metadata"
        metadata_df = pd.read_sql(metadata_query, engine)
        
        return JSONResponse(content={
            'table_id': table_id,
            'tables': metadata_df.to_dict('records')
        })
        
    except Exception as e:
        raise HTTPException(status_code=404, detail="Table not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)