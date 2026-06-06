document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("file-input");
    const btnBrowse = document.getElementById("btn-browse");
    const filesQueue = document.getElementById("files-queue");
    const queueCount = document.getElementById("queue-count");
    
    const costInputTokens = document.getElementById("cost-input-tokens");
    const costOutputTokens = document.getElementById("cost-output-tokens");
    const costAudio = document.getElementById("cost-audio");
    const costUsd = document.getElementById("cost-usd");
    const btnEstimate = document.getElementById("btn-estimate");
    
    const queryForm = document.getElementById("query-form");
    const queryText = document.getElementById("query-text");
    const chatContainer = document.getElementById("chat-container");
    const btnClearChat = document.getElementById("btn-clear-chat");
    const btnInputFile = document.getElementById("btn-input-file");
    
    const inspectPanel = document.getElementById("inspect-panel");
    const btnCloseInspect = document.getElementById("btn-close-inspect");
    const tabBtns = document.querySelectorAll(".tab-btn");
    const tabContents = document.querySelectorAll(".tab-content");
    const traceTimeline = document.getElementById("trace-timeline");
    const extractedList = document.getElementById("extracted-list");
    
    const loadingOverlay = document.getElementById("loading-overlay");
    const spinnerStatus = document.getElementById("spinner-status");

    const selectSuite = document.getElementById("select-suite");
    const selectModel = document.getElementById("select-model");

    // Dynamic model dropdown update based on suite mode selection
    selectSuite.addEventListener("change", () => {
        selectModel.innerHTML = "";
        if (selectSuite.value === "opensource") {
            const opt = document.createElement("option");
            opt.value = "llama-3.3-70b-versatile";
            opt.textContent = "llama-3.3-70b-versatile (Groq)";
            opt.selected = true;
            selectModel.appendChild(opt);
        } else {
            const models = [
                { val: "gemini-2.5-flash", text: "gemini-2.5-flash (Google)", sel: true },
                { val: "gemini-1.5-flash", text: "gemini-1.5-flash (Google)", sel: false }
            ];
            models.forEach(m => {
                const opt = document.createElement("option");
                opt.value = m.val;
                opt.textContent = m.text;
                opt.selected = m.sel;
                selectModel.appendChild(opt);
            });
        }
        triggerCostEstimation();
    });
    
    selectModel.addEventListener("change", () => {
        triggerCostEstimation();
    });

    // Queue State
    let selectedFiles = [];
    let conversationHistory = [];
    
    // Auto-adjust textarea height
    queryText.addEventListener("input", function() {
        this.style.height = "auto";
        this.style.height = (this.scrollHeight) + "px";
    });

    // File input handlers
    btnBrowse.addEventListener("click", () => fileInput.click());
    btnInputFile.addEventListener("click", () => fileInput.click());
    
    fileInput.addEventListener("change", (e) => {
        handleFiles(e.target.files);
        fileInput.value = ""; // reset
    });

    // Drag and drop events
    ["dragenter", "dragover"].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropzone.classList.add("dragover");
        }, false);
    });

    ["dragleave", "drop"].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropzone.classList.remove("dragover");
        }, false);
    });

    dropzone.addEventListener("drop", (e) => {
        const dt = e.dataTransfer;
        handleFiles(dt.files);
    });

    // Process uploaded files
    function handleFiles(files) {
        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            
            // Check if file is already in queue
            if (selectedFiles.some(f => f.name === file.name && f.size === file.size)) {
                continue;
            }
            
            selectedFiles.push(file);
        }
        updateQueueUI();
        triggerCostEstimation();
    }

    // Update the Queue list in sidebar
    function updateQueueUI() {
        filesQueue.innerHTML = "";
        queueCount.textContent = selectedFiles.length;
        
        if (selectedFiles.length === 0) {
            filesQueue.innerHTML = '<div class="empty-queue-message">No files selected</div>';
            btnEstimate.disabled = true;
            return;
        }
        
        btnEstimate.disabled = false;
        
        selectedFiles.forEach((file, index) => {
            const ext = file.name.split('.').pop().toLowerCase();
            let typeClass = "unknown";
            let icon = "fa-file";
            
            if (ext === "pdf") {
                typeClass = "pdf";
                icon = "fa-file-pdf";
            } else if (["png", "jpg", "jpeg", "webp"].includes(ext)) {
                typeClass = "image";
                icon = "fa-file-image";
            } else if (["mp3", "wav", "m4a", "ogg", "flac"].includes(ext)) {
                typeClass = "audio";
                icon = "fa-file-audio";
            }
            
            const card = document.createElement("div");
            card.className = `file-card ${typeClass}`;
            card.innerHTML = `
                <div class="file-icon-wrapper">
                    <i class="fa-solid ${icon}"></i>
                </div>
                <div class="file-details">
                    <div class="file-name clickable-preview" data-index="${index}" title="Click to preview file">${file.name}</div>
                    <div class="file-size">${formatBytes(file.size)}</div>
                </div>
                <button type="button" class="btn-remove-file" data-index="${index}" title="Remove file">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            `;
            
            filesQueue.appendChild(card);
        });

        // Add event listeners to remove buttons
        document.querySelectorAll(".btn-remove-file").forEach(btn => {
            btn.addEventListener("click", (e) => {
                const idx = parseInt(btn.getAttribute("data-index"));
                selectedFiles.splice(idx, 1);
                updateQueueUI();
                triggerCostEstimation();
            });
        });

        // Add event listeners to preview/open files in new tab
        document.querySelectorAll(".clickable-preview").forEach(el => {
            el.addEventListener("click", (e) => {
                const idx = parseInt(el.getAttribute("data-index"));
                const file = selectedFiles[idx];
                if (file) {
                    const fileURL = URL.createObjectURL(file);
                    window.open(fileURL, "_blank");
                }
            });
        });
    }

    // Helper: format file bytes size
    function formatBytes(bytes, decimals = 2) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    // Trigger cost estimation automatically on file changes or manually
    btnEstimate.addEventListener("click", () => triggerCostEstimation(true));

    async function triggerCostEstimation(force = false) {
        if (selectedFiles.length === 0 && !queryText.value.trim() && !force) {
            return;
        }

        const formData = new FormData();
        formData.append("query", queryText.value);
        formData.append("history", JSON.stringify(conversationHistory));
        formData.append("suite", selectSuite.value);
        formData.append("model", selectModel.value);
        selectedFiles.forEach(file => {
            formData.append("files", file);
        });

        try {
            const response = await fetch("/api/cost", {
                method: "POST",
                body: formData
            });
            if (response.ok) {
                const costData = await response.json();
                costInputTokens.textContent = costData.input_tokens.toLocaleString();
                costOutputTokens.textContent = costData.output_tokens.toLocaleString();
                costAudio.textContent = costData.audio_seconds > 0 ? `${costData.audio_seconds}s` : "0s";
                costUsd.textContent = `$${costData.estimated_cost_usd.toFixed(6)}`;
            }
        } catch (err) {
            console.error("Cost estimation error:", err);
        }
    }

    // Submit request Form
    queryForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const query = queryText.value.trim();
        
        // Show loading state
        spinnerStatus.textContent = selectedFiles.length > 0 ? "Extracting file contents..." : "Orchestrating agent plan...";
        loadingOverlay.classList.add("visible");

        // Push user query to history
        conversationHistory.push({ role: "user", content: query });

        const formData = new FormData();
        formData.append("query", query);
        formData.append("history", JSON.stringify(conversationHistory));
        formData.append("suite", selectSuite.value);
        formData.append("model", selectModel.value);
        selectedFiles.forEach(file => {
            formData.append("files", file);
        });

        // Add user message to chat UI
        appendMessage("user", query, selectedFiles);

        // Reset query text input
        queryText.value = "";
        queryText.style.height = "auto";

        try {
            const response = await fetch("/api/process", {
                method: "POST",
                body: formData
            });

            if (!response.ok) {
                throw new Error(`Server returned error status ${response.status}`);
            }

            const data = await response.json();
            
            // Append agent response
            appendMessage("agent", data.output, null, data);
            
            // Push agent response to history
            conversationHistory.push({ role: "assistant", content: data.output });
            
            // Retain files in the queue after successful execution
            updateQueueUI();
            
            // Reset cost card values to show actual run cost
            costInputTokens.textContent = data.cost.input_tokens.toLocaleString();
            costOutputTokens.textContent = data.cost.output_tokens.toLocaleString();
            costAudio.textContent = data.cost.audio_seconds > 0 ? `${data.cost.audio_seconds}s` : "0s";
            costUsd.textContent = `$${data.cost.estimated_cost_usd.toFixed(6)}`;

            // Populate Inspection drawer
            populateInspector(data);
            
            // Open Inspector drawer
            inspectPanel.classList.add("open");

        } catch (error) {
            console.error("Processing query failed:", error);
            appendMessage("agent", `⚠️ Error: Could not complete your request. Details: ${error.message}`);
        } finally {
            loadingOverlay.classList.remove("visible");
        }
    });

    // Populate the Inspector Drawer Tab Panels
    function populateInspector(data) {
        // Tab 1: Reasoning Trace
        traceTimeline.innerHTML = "";
        if (!data.trace || data.trace.length === 0) {
            traceTimeline.innerHTML = '<p class="empty-state">No execution trace steps logged.</p>';
        } else {
            data.trace.forEach(node => {
                const nodeDiv = document.createElement("div");
                nodeDiv.className = `trace-node ${node.type}`;
                
                let detailHtml = "";
                if (node.details) {
                    detailHtml = `<pre class="trace-details"><code>${JSON.stringify(node.details, null, 2)}</code></pre>`;
                }
                
                nodeDiv.innerHTML = `
                    <div class="trace-step-number">Step ${node.step} (${node.type})</div>
                    <div class="trace-reasoning">${node.reasoning}</div>
                    ${detailHtml}
                `;
                traceTimeline.appendChild(nodeDiv);
            });
        }

        // Tab 2: Extracted Content
        extractedList.innerHTML = "";
        if (!data.extracted_content || data.extracted_content.length === 0) {
            extractedList.innerHTML = '<p class="empty-state">No files were parsed for this query.</p>';
        } else {
            data.extracted_content.forEach(item => {
                const itemDiv = document.createElement("div");
                itemDiv.className = "extracted-item";
                
                let metaText = item.method || "";
                if (item.confidence) metaText += ` | Conf: ${item.confidence.toFixed(2)}`;
                if (item.duration) metaText += ` | Duration: ${item.duration}s`;
                
                itemDiv.innerHTML = `
                    <div class="extracted-item-header">
                        <div class="extracted-item-title">
                            <i class="fa-solid fa-file-invoice"></i> ${item.name}
                        </div>
                        <div class="extracted-item-meta">${metaText}</div>
                    </div>
                    <div class="extracted-item-body">${escapeHTML(item.extracted_text || item.error || "Empty Text")}</div>
                `;
                extractedList.appendChild(itemDiv);
            });
        }
    }

    // Helper: Escapes HTML to prevent injection and render tags correctly
    function escapeHTML(str) {
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Append standard messages to the Chat Scroll pane
    function appendMessage(sender, text, files = null, fullResponseData = null) {
        const msg = document.createElement("div");
        msg.className = `message ${sender}-message`;
        
        let avatarIcon = sender === "user" ? "fa-user" : "fa-robot";
        let messageTextFormatted = text;
        
        // Simple markdown code rendering for Agent messages
        if (sender === "agent") {
            messageTextFormatted = formatMarkdown(text);
        }

        let fileTagsHtml = "";
        if (files && files.length > 0) {
            fileTagsHtml = `<div class="message-files-tag">`;
            files.forEach(file => {
                fileTagsHtml += `<span class="msg-file-pill"><i class="fa-solid fa-paperclip"></i> ${file.name}</span>`;
            });
            fileTagsHtml += `</div>`;
        }

        let metaLinksHtml = "";
        if (sender === "agent" && fullResponseData) {
            metaLinksHtml = `
                <div class="message-meta">
                    <button class="btn-meta" id="btn-inspect-trigger">
                        <i class="fa-solid fa-chart-line"></i> Inspect Trace
                    </button>
                </div>
            `;
        }

        msg.innerHTML = `
            <div class="message-avatar">
                <i class="fa-solid ${avatarIcon}"></i>
            </div>
            <div class="message-content">
                ${messageTextFormatted}
                ${fileTagsHtml}
                ${metaLinksHtml}
            </div>
        `;
        
        chatContainer.appendChild(msg);
        chatContainer.scrollTop = chatContainer.scrollHeight;

        // Hook up inspect triggers in message
        const trigger = msg.querySelector("#btn-inspect-trigger");
        if (trigger) {
            trigger.addEventListener("click", () => {
                populateInspector(fullResponseData);
                inspectPanel.classList.add("open");
            });
        }
    }

    // Clean markdown bolding, code segments, and bullet points
    // Comprehensive markdown parser for headings, lists, tables, bold, and code blocks
    function formatMarkdown(text) {
        // Escapes HTML tags first
        let html = escapeHTML(text);
        
        // Extract and safeguard code blocks from line-by-line processing
        const codeBlocks = [];
        html = html.replace(/```([\s\S]+?)```/g, (match, code) => {
            const placeholder = `__CODEBLOCK_PLACEHOLDER_${codeBlocks.length}__`;
            codeBlocks.push(`<pre><code>${code}</code></pre>`);
            return placeholder;
        });

        // Split text into lines
        const lines = html.split('\n');
        const formattedLines = [];
        
        let inTable = false;
        let tableHeader = null;
        let tableRows = [];
        let inList = false;
        let listType = null; // 'ul' or 'ol'
        
        for (let i = 0; i < lines.length; i++) {
            let line = lines[i].trim();
            
            // Check for table row
            const isTableRow = line.startsWith('|') && line.endsWith('|');
            
            if (isTableRow) {
                if (inList) {
                    formattedLines.push(`</${listType}>`);
                    inList = false;
                    listType = null;
                }
                
                let cells = line.split('|').map(c => c.trim());
                if (cells[0] === '') cells.shift();
                if (cells[cells.length - 1] === '') cells.pop();
                
                const isSeparatorRow = cells.every(c => /^:?-+:?$/.test(c));
                
                if (isSeparatorRow) {
                    continue;
                }
                
                if (!inTable) {
                    inTable = true;
                    tableHeader = cells;
                    tableRows = [];
                } else {
                    tableRows.push(cells);
                }
                continue;
            } else {
                if (inTable) {
                    let tableHtml = '<table class="markdown-table">';
                    if (tableHeader) {
                        tableHtml += '<thead><tr>';
                        tableHeader.forEach(h => {
                            tableHtml += `<th>${formatInlineMarkdown(h)}</th>`;
                        });
                        tableHtml += '</tr></thead>';
                    }
                    tableHtml += '<tbody>';
                    tableRows.forEach(row => {
                        tableHtml += '<tr>';
                        row.forEach(c => {
                            tableHtml += `<td>${formatInlineMarkdown(c || '')}</td>`;
                        });
                        tableHtml += '</tr>';
                    });
                    tableHtml += '</tbody></table>';
                    formattedLines.push(tableHtml);
                    
                    inTable = false;
                    tableHeader = null;
                    tableRows = [];
                }
            }
            
            // Check for headers
            const headerMatch = line.match(/^(#{1,6})\s+(.+)$/);
            if (headerMatch) {
                if (inList) {
                    formattedLines.push(`</${listType}>`);
                    inList = false;
                    listType = null;
                }
                const level = headerMatch[1].length;
                const content = headerMatch[2];
                formattedLines.push(`<h${level}>${formatInlineMarkdown(content)}</h${level}>`);
                continue;
            }
            
            // Check for list items
            const ulMatch = line.match(/^[-*+]\s+(.+)$/);
            const olMatch = line.match(/^(\d+)\.\s+(.+)$/);
            
            if (ulMatch) {
                if (!inList || listType !== 'ul') {
                    if (inList) {
                        formattedLines.push(`</${listType}>`);
                    }
                    formattedLines.push('<ul>');
                    inList = true;
                    listType = 'ul';
                }
                formattedLines.push(`<li>${formatInlineMarkdown(ulMatch[1])}</li>`);
                continue;
            } else if (olMatch) {
                if (!inList || listType !== 'ol') {
                    if (inList) {
                        formattedLines.push(`</${listType}>`);
                    }
                    formattedLines.push('<ol>');
                    inList = true;
                    listType = 'ol';
                }
                formattedLines.push(`<li>${formatInlineMarkdown(olMatch[2])}</li>`);
                continue;
            } else {
                if (inList) {
                    formattedLines.push(`</${listType}>`);
                    inList = false;
                    listType = null;
                }
            }
            
            // Horizontal rule
            if (/^(?:-{3,}|\*{3,}|\_{3,})$/.test(line)) {
                formattedLines.push('<hr>');
                continue;
            }
            
            // Empty line
            if (line === '') {
                formattedLines.push('<br>');
                continue;
            }
            
            // Regular line
            formattedLines.push(formatInlineMarkdown(line));
        }
        
        if (inList) {
            formattedLines.push(`</${listType}>`);
        }
        if (inTable) {
            let tableHtml = '<table class="markdown-table">';
            if (tableHeader) {
                tableHtml += '<thead><tr>';
                tableHeader.forEach(h => {
                    tableHtml += `<th>${formatInlineMarkdown(h)}</th>`;
                });
                tableHtml += '</tr></thead>';
            }
            tableHtml += '<tbody>';
            tableRows.forEach(row => {
                tableHtml += '<tr>';
                row.forEach(c => {
                    tableHtml += `<td>${formatInlineMarkdown(c || '')}</td>`;
                });
                tableHtml += '</tr>';
            });
            tableHtml += '</tbody></table>';
            formattedLines.push(tableHtml);
        }
        
        let finalHtml = formattedLines.map((l) => {
            const trimmed = l.trim();
            if (trimmed.startsWith('<h') || trimmed.startsWith('<ul') || trimmed.startsWith('<ol') || trimmed.startsWith('<li') || trimmed.startsWith('</ul') || trimmed.startsWith('</ol') || trimmed.startsWith('<table') || trimmed.startsWith('<tr') || trimmed.startsWith('<td') || trimmed.startsWith('<th') || trimmed.startsWith('</tr') || trimmed.startsWith('</table') || trimmed.startsWith('<hr') || trimmed.startsWith('<br>')) {
                return l;
            }
            return l + '<br>';
        }).join('\n');
        
        // Restore code blocks
        codeBlocks.forEach((block, idx) => {
            finalHtml = finalHtml.replace(`__CODEBLOCK_PLACEHOLDER_${idx}__`, block);
        });
        
        return finalHtml;
    }
    
    // Helper to format inline markdown inside blocks
    function formatInlineMarkdown(text) {
        // Inline code: `code`
        text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
        // Bold: **text**
        text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        // Italics: *text* or _text_
        text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        text = text.replace(/_([^_]+)_/g, '<em>$1</em>');
        return text;
    }

    // Close Inspect Drawer
    btnCloseInspect.addEventListener("click", () => {
        inspectPanel.classList.remove("open");
    });

    // Handle inspect tab buttons switching
    tabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            tabBtns.forEach(b => b.classList.remove("active"));
            tabContents.forEach(tc => tc.classList.remove("active"));
            
            btn.classList.add("active");
            const targetTab = btn.getAttribute("data-tab");
            document.getElementById(targetTab).classList.add("active");
        });
    });

    // Clear chat display screen
    btnClearChat.addEventListener("click", () => {
        chatContainer.innerHTML = "";
        conversationHistory = []; // Reset history
        inspectPanel.classList.remove("open");
        traceTimeline.innerHTML = '<p class="empty-state">Run a query to inspect the agent\'s tool execution steps.</p>';
        extractedList.innerHTML = '<p class="empty-state">Extracted file data will be displayed here.</p>';
        
        // Append initial system message
        const welcomeMsg = document.createElement("div");
        welcomeMsg.className = "message system-message";
        welcomeMsg.innerHTML = `
            <div class="message-avatar">
                <i class="fa-solid fa-robot"></i>
            </div>
            <div class="message-content">
                <h3>Welcome to Data Smith AI!</h3>
                <p>I am an autonomous planning agent. Upload files (PDFs, Images, Audio) and enter instructions to get started. I can:</p>
                <ul>
                    <li>Extract and run OCR/transcriptions automatically.</li>
                    <li>Resolve links (e.g. YouTube URLs) inside documents.</li>
                    <li>Chain multiple tools like summaries, sentiments, code analyses, and reasoning.</li>
                    <li>Ask follow-up clarification questions if instructions are vague.</li>
                </ul>
            </div>
        `;
        chatContainer.appendChild(welcomeMsg);
        
        // Reset cost tracker labels
        costInputTokens.textContent = "0";
        costOutputTokens.textContent = "0";
        costAudio.textContent = "0s";
        costUsd.textContent = "$0.000000";
    });
});
