import React, { useState, useRef, useEffect } from "react";
import axios from "axios";
import Plot from "react-plotly.js";
import "./App.css";

const API_BASE_URL = process.env.REACT_APP_API_URL || "http://localhost:8000";

function App() {
  const [uploadedFile, setUploadedFile] = useState(null);
  const [tableId, setTableId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [currentQuery, setCurrentQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(scrollToBottom, [messages]);

  const handleFileUpload = async (file) => {
    if (!file) return;

    setIsLoading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await axios.post(`${API_BASE_URL}/upload`, formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });

      setUploadedFile(response.data);
      setTableId(response.data.table_id);

      // Add success message
      setMessages([
        {
          type: "system",
          content: `✅ File "${response.data.filename}" uploaded successfully! 
        Found ${
          Object.keys(response.data.sheets).length
        } sheet(s) with ${Object.values(response.data.sheets).reduce(
            (total, sheet) => total + sheet.shape[0],
            0
          )} total rows.
        
        You can now ask questions about your data. Try:
        • "Show me a summary of the data"
        • "What are the trends over time?"
        • "Create a chart showing the top categories"`,
          timestamp: new Date().toLocaleTimeString(),
        },
      ]);
    } catch (error) {
      console.error("Upload error:", error);
      setMessages([
        {
          type: "error",
          content: `❌ Upload failed: ${
            error.response?.data?.detail || error.message
          }`,
          timestamp: new Date().toLocaleTimeString(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      handleFileUpload(files[0]);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setDragOver(false);
  };

  const handleFileSelect = (e) => {
    const file = e.target.files[0];
    if (file) {
      handleFileUpload(file);
    }
  };

  const handleQuerySubmit = async (e) => {
    e.preventDefault();
    if (!currentQuery.trim() || !tableId || isLoading) return;

    const userMessage = {
      type: "user",
      content: currentQuery,
      timestamp: new Date().toLocaleTimeString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setCurrentQuery("");
    setIsLoading(true);

    try {
      const response = await axios.post(`${API_BASE_URL}/query`, {
        table_id: tableId,
        question: currentQuery,
      });

      const botMessage = {
        type: "bot",
        content: response.data.explanation,
        data: response.data.data,
        chart: response.data.chart,
        insights: response.data.insights,
        success: response.data.success,
        timestamp: new Date().toLocaleTimeString(),
      };

      setMessages((prev) => [...prev, botMessage]);
    } catch (error) {
      console.error("Query error:", error);
      const errorMessage = {
        type: "error",
        content: `❌ Query failed: ${
          error.response?.data?.detail || error.message
        }`,
        timestamp: new Date().toLocaleTimeString(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const renderMessage = (message, index) => {
    const { type, content, data, chart, insights, timestamp } = message;

    return (
      <div key={index} className={`message ${type}`}>
        <div className="message-header">
          <span className={`message-type ${type}`}>
            {type === "user" && "👤"}
            {type === "bot" && "🤖"}
            {type === "system" && "💡"}
            {type === "error" && "⚠️"}
          </span>
          <span className="timestamp">{timestamp}</span>
        </div>

        <div className="message-content">
          <p>{content}</p>

          {insights && (
            <div className="insights">
              <h4>💡 Insights:</h4>
              <p>{insights}</p>
            </div>
          )}

          {chart && chart.type === "table" && data && (
            <div className="data-table">
              <h4>📊 Results ({data.length} rows):</h4>
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      {Object.keys(data[0] || {}).map((key) => (
                        <th key={key}>{key}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.slice(0, 10).map((row, i) => (
                      <tr key={i}>
                        {Object.values(row).map((value, j) => (
                          <td key={j}>{String(value)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {data.length > 10 && (
                  <p className="table-footer">
                    Showing first 10 of {data.length} rows
                  </p>
                )}
              </div>
            </div>
          )}

          {chart && chart.type !== "table" && chart.plotly_json && (
            <div className="chart-container">
              <h4>📊 Visualization:</h4>
              <Plot
                data={chart.plotly_json.data}
                layout={{
                  ...chart.plotly_json.layout,
                  autosize: true,
                  margin: { t: 40, r: 20, b: 40, l: 60 },
                }}
                style={{ width: "100%", height: "400px" }}
                config={{ responsive: true, displayModeBar: false }}
              />
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>🤖 AI Data Agent</h1>
        <p>Upload your Excel files and ask questions in natural language</p>
      </header>

      <div className="app-content">
        {!uploadedFile ? (
          <div className="upload-section">
            <div
              className={`upload-area ${dragOver ? "drag-over" : ""}`}
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onClick={() => fileInputRef.current?.click()}
            >
              <div className="upload-content">
                <div className="upload-icon">📊</div>
                <h3>Upload Your Excel File</h3>
                <p>
                  Drag and drop your .xlsx or .xls file here, or click to browse
                </p>
                <div className="upload-features">
                  <span>✅ Handles messy data</span>
                  <span>✅ Multiple sheets support</span>
                  <span>✅ Auto data cleaning</span>
                </div>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.xls"
                onChange={handleFileSelect}
                style={{ display: "none" }}
              />
            </div>

            {isLoading && (
              <div className="loading">
                <div className="spinner"></div>
                <p>Processing your Excel file...</p>
              </div>
            )}
          </div>
        ) : (
          <div className="chat-section">
            <div className="file-info">
              <h3>📁 {uploadedFile.filename}</h3>
              <div className="file-details">
                {Object.entries(uploadedFile.sheets).map(
                  ([sheetName, info]) => (
                    <span key={sheetName} className="sheet-tag">
                      {sheetName} ({info.shape[0]} rows, {info.shape[1]} cols)
                    </span>
                  )
                )}
              </div>
              <button
                className="new-file-btn"
                onClick={() => {
                  setUploadedFile(null);
                  setTableId(null);
                  setMessages([]);
                  setCurrentQuery("");
                }}
              >
                Upload New File
              </button>
            </div>

            <div className="messages-container">
              {messages.map((message, index) => renderMessage(message, index))}
              {isLoading && (
                <div className="message bot loading-message">
                  <div className="message-header">
                    <span className="message-type bot">🤖</span>
                  </div>
                  <div className="message-content">
                    <div className="typing-indicator">
                      <span></span>
                      <span></span>
                      <span></span>
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            <form className="query-form" onSubmit={handleQuerySubmit}>
              <div className="input-container">
                <input
                  type="text"
                  value={currentQuery}
                  onChange={(e) => setCurrentQuery(e.target.value)}
                  placeholder="Ask a question about your data... (e.g., 'Show me sales trends by month')"
                  disabled={isLoading}
                  className="query-input"
                />
                <button
                  type="submit"
                  disabled={!currentQuery.trim() || isLoading}
                  className="send-button"
                >
                  {isLoading ? "⏳" : "🚀"}
                </button>
              </div>
              <div className="suggested-queries">
                <span>💡 Try:</span>
                <button
                  type="button"
                  onClick={() =>
                    setCurrentQuery("Show me a summary of all the data")
                  }
                  className="suggestion-btn"
                >
                  Summary
                </button>
                <button
                  type="button"
                  onClick={() => setCurrentQuery("What are the top 10 values?")}
                  className="suggestion-btn"
                >
                  Top 10
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setCurrentQuery("Create a chart showing trends over time")
                  }
                  className="suggestion-btn"
                >
                  Trends
                </button>
              </div>
            </form>
          </div>
        )}
      </div>

      <footer className="app-footer">
        <p>Built with React, FastAPI, and AI • Handles any Excel format</p>
      </footer>
    </div>
  );
}

export default App;
