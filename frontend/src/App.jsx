import { useState, useEffect, useRef } from "react";
import axios from "axios";
import "./App.css";

const API_BASE = import.meta.env.DEV ? "http://127.0.0.1:8000" : "";

function App() {
  const [file, setFile] = useState(null);
  const [message, setMessage] = useState("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [typingText, setTypingText] = useState("");
  const [displayedTyping, setDisplayedTyping] = useState("");
  const [currentSources, setCurrentSources] = useState([]);

  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({
      behavior: "smooth",
    });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, displayedTyping, thinking]);

  useEffect(() => {
    if (!typingText) {
      setDisplayedTyping("");
      return;
    }

    let i = 0;
    const interval = setInterval(() => {
      setDisplayedTyping(typingText.slice(0, i + 1));
      i++;

      if (i >= typingText.length) {
        clearInterval(interval);
        setMessages((prev) => [
          ...prev,
          {
            id: Date.now(),
            sender: "bot",
            text: typingText,
            sources: currentSources,
          },
        ]);
        setTypingText("");
        setDisplayedTyping("");
        setCurrentSources([]);
      }
    }, 15);

    return () => clearInterval(interval);
  }, [typingText, currentSources]);

  const uploadFile = async () => {
    if (!file) return;
    setUploading(true);
    setMessage("");

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await axios.post(`${API_BASE}/upload`, formData);
      setMessage(response.data.message);
    } catch (err) {
      console.log(err);
      const detail = err.response?.data?.detail;
      setMessage(detail ? `Upload failed: ${detail}` : "Upload Failed");
    }
    setUploading(false);
  };

  const handleSend = async () => {
    if (!input.trim()) return;

    const question = input;
    setMessages((prev) => [
      ...prev,
      {
        id: Date.now(),
        sender: "user",
        text: question,
      },
    ]);

    setInput("");
    setThinking(true);

    try {
      const response = await axios.post(
        `${API_BASE}/chat?question=${encodeURIComponent(question)}`
      );
      setThinking(false);
      setCurrentSources(response.data.sources || []);
      setTypingText(response.data.answer);
    } catch (err) {
      console.log(err);
      setThinking(false);
      const detail = err.response?.data?.detail;
      setCurrentSources([]);
      setTypingText(detail || "Unable to connect to server.");
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!thinking && !typingText) {
        handleSend();
      }
    }
  };

  return (
    <div className="app-container">
      {/* Left Panel: Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1 className="brand-logo">HelpMe</h1>
          <p className="brand-subtitle">Document Search & RAG System</p>
        </div>

        <div className="sidebar-section">
          <h2 className="section-title">Ingest Document</h2>
          <p className="section-description">
            Upload a PDF file to process and build a semantic search index.
          </p>

          <label className="compact-upload-card">
            <input
              type="file"
              accept="application/pdf"
              onChange={(e) => setFile(e.target.files[0])}
            />
            <span className="upload-icon">📄</span>
            <div className="upload-details">
              <span className="file-status">
                {file ? file.name : "Select PDF Document"}
              </span>
              <span className="upload-action-text">Click to browse</span>
            </div>
          </label>

          <button
            className="action-btn"
            onClick={uploadFile}
            disabled={!file || uploading}
          >
            {uploading ? "Ingesting..." : "Process File"}
          </button>
        </div>

        {message && (
          <div className="notification-banner">
            {message}
          </div>
        )}
      </aside>

      {/* Right Panel: Content / Chat */}
      <main className="main-content">

        <div className="chat-window">
          {messages.length === 0 && !thinking && !typingText && (
            <div className="workspace-welcome">
              <h2>Start Exploring</h2>
              <p>
                Upload a document on the left sidebar. Ask questions about the
                content, and retrieve information with direct page citations.
              </p>
            </div>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`chat-row ${
                msg.sender === "user" ? "user-row" : "system-row"
              }`}
            >
              <div className="chat-bubble">
                <div className="chat-text">{msg.text}</div>
                {msg.sources && msg.sources.length > 0 && (
                  <div className="sources-wrapper">
                    <span className="sources-header">Cited Pages:</span>
                    <div className="sources-list">
                      {msg.sources.map((src, idx) => (
                        <span
                          key={idx}
                          className="source-pill"
                          title={`Similarity Score: ${src.distance}`}
                        >
                          Page {src.pages}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}

          {thinking && (
            <div className="chat-row system-row">
              <div className="chat-bubble loading-bubble">
                <div className="typing-loader">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            </div>
          )}

          {typingText && (
            <div className="chat-row system-row">
              <div className="chat-bubble">
                <div className="chat-text">{displayedTyping}</div>
                <span className="typing-cursor"></span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef}></div>
        </div>

        <div className="bottom-dock">
          <div className="input-box-wrapper">
            <input
              className="chat-field"
              type="text"
              placeholder="Search document content..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={thinking || typingText !== ""}
            />
            <button
              className="send-trigger"
              onClick={handleSend}
              disabled={!input.trim() || thinking || typingText !== ""}
            >
              Ask
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;