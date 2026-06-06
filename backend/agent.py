import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import pydantic

from backend import config
from backend import tools
from backend import llm

# Configure logging
logger = logging.getLogger(__name__)

class ToolArgsModel(pydantic.BaseModel):
    url: Optional[str] = None
    text: Optional[str] = None
    code: Optional[str] = None
    query: Optional[str] = None

class ToolCallModel(pydantic.BaseModel):
    tool: str  # "fetch_youtube_transcript", "summarize_text", "analyze_sentiment", "explain_code", "conversational_answer"
    args: ToolArgsModel

class AgentPlanModel(pydantic.BaseModel):
    type: str  # "clarify", "tool_call", "finish"
    question: Optional[str] = None  # used when type is "clarify"
    tool_calls: Optional[List[ToolCallModel]] = None  # used when type is "tool_call"
    reasoning: str  # explanation of the decision

class CostTracker:
    """Estimates and records API usage and token costs based on official model documentation pricing."""
    
    def __init__(self, suite: str = "proprietary", model_name: str = "gemini-2.5-flash"):
        self.suite = suite
        self.model_name = model_name
        self.input_tokens = 0
        self.output_tokens = 0
        self.image_count = 0
        self.audio_seconds = 0.0
        self.direct_cost = 0.0
        
        # Official rate mapping:
        # Gemini 1.5/2.5 Flash standard pricing on Google AI Studio:
        # Input: $0.075 / million tokens ($0.000000075 / token)
        # Output: $0.30 / million tokens ($0.0000003 / token)
        # Gemini Image: 258 tokens per image
        # Gemini Audio: 12.5 tokens per second
        #
        # Groq Llama 3.3 70B pricing:
        # Input: $0.59 / million tokens ($0.00000059 / token)
        # Output: $0.79 / million tokens ($0.00000079 / token)
        # Groq Whisper audio pricing:
        # ~$0.00016 per minute ($0.0000027 / second)
        # Hugging Face Vision serverless call pricing:
        # Estimated compute usage equivalent to $0.00005 per OCR call
        
        if suite == "opensource" or model_name == "llama-3.3-70b-versatile":
            self.input_rate = 0.59 / 1_000_000
            self.output_rate = 0.79 / 1_000_000
        else:
            self.input_rate = 0.075 / 1_000_000
            self.output_rate = 0.30 / 1_000_000
        
    def add_text_input(self, text: str):
        self.input_tokens += max(1, len(text) // 4)
        
    def add_text_output(self, text: str):
        self.output_tokens += max(1, len(text) // 4)
        
    def add_image(self):
        self.image_count += 1
        if self.suite == "opensource":
            self.direct_cost += 0.00005  # HF serverless API call estimate
        else:
            self.input_tokens += 258      # Gemini standard image token count
        
    def add_audio(self, duration: float):
        self.audio_seconds += duration
        if self.suite == "opensource":
            self.direct_cost += duration * 0.0000027  # Groq Whisper rates
        else:
            self.input_tokens += int(duration * 12.5)  # Gemini standard audio token count
        
    def add_direct_cost(self, cost: float):
        self.direct_cost += cost

    def get_totals(self) -> Dict[str, Any]:
        calculated_cost = (
            (self.input_tokens * self.input_rate) +
            (self.output_tokens * self.output_rate) +
            self.direct_cost
        )
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "image_count": self.image_count,
            "audio_seconds": round(self.audio_seconds, 2),
            "estimated_cost_usd": round(calculated_cost, 6)
        }


class AgentOrchestrator:
    """Manages the lifecycle of an agent request: Ingestion, Planning, Tool Execution, and Synthesis."""
            
    def ingest_files(
        self,
        file_infos: List[Dict[str, Any]],
        cost_tracker: CostTracker,
        suite: str = "proprietary",
        model_name: str = "gemini-2.5-flash"
    ) -> List[Dict[str, Any]]:
        """
        Processes files programmatically and extracts text contents.
        """
        extracted_data = []
        
        for file in file_infos:
            file_name = file["name"]
            file_path = Path(file["path"])
            file_type = file["type"]
            
            logger.info(f"Ingesting file: {file_name} ({file_type}) using suite={suite}")
            
            try:
                if file_type == "pdf":
                    cost_tracker.add_text_input(file_name)
                    # pypdf reading
                    result = tools.extract_pdf_text(file_path, suite, model_name)
                    
                    if result.get("method") in ["gemini_pdf_ocr", "huggingface_llama_vision_ocr", "huggingface_aya_vision_ocr"]:
                        cost_tracker.add_image()
                    
                    extracted_data.append({
                        "name": file_name,
                        "type": file_type,
                        "extracted_text": result.get("text", ""),
                        "confidence": result.get("confidence", 1.0),
                        "method": result.get("method", "native")
                    })
                    
                elif file_type in ["image", "png", "jpg", "jpeg"]:
                    cost_tracker.add_image()
                    result = tools.ocr_image(file_path, suite, model_name)
                    extracted_data.append({
                        "name": file_name,
                        "type": file_type,
                        "extracted_text": result.get("text", ""),
                        "confidence": result.get("confidence", 0.9),
                        "method": result.get("method", "ocr")
                    })
                    
                elif file_type in ["audio", "mp3", "wav", "m4a"]:
                    # Get duration
                    duration = tools.get_audio_duration(file_path)
                    cost_tracker.add_audio(duration)
                    
                    result = tools.transcribe_audio(file_path, suite, model_name)
                    extracted_data.append({
                        "name": file_name,
                        "type": file_type,
                        "extracted_text": result.get("text", ""),
                        "duration": result.get("duration", duration),
                        "method": result.get("method", "transcription")
                    })
                else:
                    extracted_data.append({
                        "name": file_name,
                        "type": file_type,
                        "error": f"Unsupported file type: {file_type}"
                    })
            except Exception as e:
                logger.error(f"Error ingesting {file_name}: {e}", exc_info=True)
                extracted_data.append({
                    "name": file_name,
                    "type": file_type,
                    "error": str(e)
                })
                
        return extracted_data

    def estimate_plan_cost(
        self,
        query: str,
        file_infos: List[Dict[str, Any]],
        suite: str = "proprietary",
        model_name: str = "gemini-2.5-flash",
        history_list: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Estimates the cost of a query plan before execution based on static inputs.
        """
        import pypdf
        import re
        tracker = CostTracker(suite, model_name)
        tracker.add_text_input(query)
        
        # Regex to scan for YouTube video links
        yt_pattern = r"(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be)\/(?:watch\?v=|embed\/|shorts\/)?([0-9A-Za-z_-]{11})"
        youtube_urls = []
        
        # Scan user query for links
        for match in re.finditer(yt_pattern, query):
            youtube_urls.append(match.group(0))
            
        # Scan conversation history for links
        if history_list:
            for msg in history_list:
                msg_content = msg.get("content", "")
                if msg_content:
                    for match in re.finditer(yt_pattern, msg_content):
                        youtube_urls.append(match.group(0))
                        
        # Keep unique URLs
        youtube_urls = list(set(youtube_urls))
        
        extracted_text_len = 0
        for file in file_infos:
            file_path = Path(file["path"])
            file_type = file["type"]
            
            if file_type == "pdf":
                try:
                    reader = pypdf.PdfReader(str(file_path))
                    pdf_text = ""
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            pdf_text += page_text + "\n"
                    pdf_text = pdf_text.strip()
                    if pdf_text:
                        extracted_text_len += len(pdf_text)
                        # Scan PDF text for YouTube links
                        for match in re.finditer(yt_pattern, pdf_text):
                            youtube_urls.append(match.group(0))
                    else:
                        tracker.add_image()  # Scanned PDF fallback
                except Exception:
                    extracted_text_len += 2000  # Estimate 2000 chars if read fails
                    
            elif file_type in ["image", "png", "jpg", "jpeg"]:
                tracker.add_image()
                extracted_text_len += 500  # Expected OCR text size
                
            elif file_type in ["audio", "mp3", "wav", "m4a"]:
                duration = tools.get_audio_duration(file_path)
                tracker.add_audio(duration)
                extracted_text_len += int(duration * 15)  # Expected transcript size
                
        # Estimate YouTube transcript sizes
        youtube_transcript_len = 0
        for yt_url in youtube_urls:
            try:
                # Attempt to pre-fetch the transcript metadata size
                res = tools.fetch_youtube_transcript(yt_url)
                if "text" in res:
                    youtube_transcript_len += len(res["text"])
                else:
                    youtube_transcript_len += 4000  # Estimate 1000 tokens (4000 chars) if error
            except Exception:
                youtube_transcript_len += 4000      # Fallback
                
        # Estimate average workflow usage: 1 planning ReAct step + 1 synthesis step
        history_chars = 0
        if history_list:
            history_chars = sum(len(m.get("content", "")) for m in history_list)
            
        # Planning loop step input:
        planner_input_chars = len(query) + extracted_text_len + youtube_transcript_len + history_chars + 500
        tracker.input_tokens += max(1, planner_input_chars // 4)
        tracker.output_tokens += 120  # Average plan JSON tokens
        
        # Synthesis step input:
        synthesis_input_chars = len(query) + extracted_text_len + youtube_transcript_len + history_chars + 800
        tracker.input_tokens += max(1, synthesis_input_chars // 4)
        tracker.output_tokens += 350  # Average answer tokens
        
        return tracker.get_totals()

    def process_query(
        self,
        query: str,
        file_infos: List[Dict[str, Any]],
        suite: str = "proprietary",
        model_name: str = "gemini-2.5-flash",
        history_list: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Runs the agentic loop to process user query + file inputs.
        """
        cost_tracker = CostTracker(suite, model_name)
        
        # Format conversation history context
        history_context = ""
        if history_list:
            history_context = "Conversation history (recent exchanges):\n"
            for msg in history_list:
                role = "User" if msg.get("role") == "user" else "Assistant"
                history_context += f"- {role}: {msg.get('content')}\n"
            history_context += "\n"
        trace = []
        
        # 1. Ingest files
        cost_tracker.add_text_input(query)
        extracted_content = self.ingest_files(file_infos, cost_tracker, suite, model_name)
        
        # Format the file context for the LLM
        context_parts = []
        for content in extracted_content:
            if "error" in content:
                context_parts.append(f"File '{content['name']}' Error: {content['error']}")
            else:
                meta = ""
                if "confidence" in content:
                    meta += f" (OCR Confidence: {content['confidence']})"
                if "duration" in content:
                    meta += f" (Audio Duration: {content['duration']}s)"
                    
                context_parts.append(
                    f"File '{content['name']}' ({content['type']}){meta}:\n"
                    f"--- START EXTRACTED TEXT ---\n"
                    f"{content['extracted_text']}\n"
                    f"--- END EXTRACTED TEXT ---"
                )
        
        file_context = "\n\n".join(context_parts)
        
        # Keep track of agent state
        history = []
        max_iterations = 4
        final_answer = None
        clarifying_question = None
        
        # 2. ReAct loop
        for step_idx in range(max_iterations):
            logger.info(f"Agent Orchestrator planning step {step_idx} (Suite: {suite}, Model: {model_name})")
            
            # Construct system prompt
            planner_prompt = (
                "You are an AI Agent Planner. You analyze the user's query, the files context, "
                "and execution history to coordinate tasks. You can run one or more tools in parallel if they "
                "don't depend on each other.\n\n"
                "CONTEXT RESOLUTION GUIDELINES:\n"
                "- The user query might refer to files, links, code, or context using pronouns/references like 'it', 'this', 'that video', 'the file', 'the code', 'the text', etc.\n"
                "- You MUST look at both the current 'Files Context' and the 'Conversation history (recent exchanges)' to resolve these references. DO NOT ask the user for information (such as a URL or a file) if it is already present in the history or current context.\n"
                "- For example, if a YouTube URL or a PDF file was mentioned/uploaded in previous exchanges, and the user now asks 'summarize it' or 'explain it', resolve 'it' to that URL/file and call the corresponding tool immediately.\n\n"
                "MANDATORY CLARIFICATION RULE:\n"
                "- If the input (current query, files context, and conversation history) does NOT contain enough information to determine the task, or if multiple tasks are equally plausible, you MUST NOT guess. You MUST ask a short, clear follow-up question (type='clarify').\n"
                "- If you determine that a clarifying question is needed, set type='clarify' and set the 'question' field to a short, clear question. Do NOT execute any other tool calls first. You must only proceed after receiving clarity.\n"
                "- You MUST use or base your question on the following exact examples depending on the ambiguity:\n"
                "  * \"Could you clarify whether you want a summary or sentiment analysis?\" (e.g. if the user provides text or a text file but does not specify the task type or if they ask to 'process' or 'analyze' it generally)\n"
                "  * \"What do you want me to do with this extracted text?\" (e.g. if text is extracted from a file but there is no instruction on what to do with it)\n"
                "  * \"Should I explain this code or rewrite it?\" (e.g. if the user provides code but does not specify whether to explain, rewrite, optimize, etc. - e.g. asking generally to 'analyze this code')\n"
                "- IMPORTANT: If the user provides a code snippet or a file containing code, and asks to 'analyze', 'process', or 'look at' the code without specifying if they want it explained, rewritten, refactored, or optimized, this is ambiguous. Do NOT guess or call `explain_code` or any other tool. You MUST ask: 'Should I explain this code or rewrite it?'\n"
                "- IMPORTANT: If the user provides general text or a file containing text and asks to 'process', 'analyze', or 'look at' it generally without specifying the task, this is ambiguous. Do NOT guess or call `summarize_text`/`analyze_sentiment`. You MUST ask: 'Could you clarify whether you want a summary or sentiment analysis?'\n"
                "- IMPORTANT: If text is extracted from an uploaded file but the user does not provide any instruction or query at all, this is ambiguous. You MUST ask: 'What do you want me to do with this extracted text?'\n\n"
                "NO UNNECESSARY CLARIFICATION (CRITICAL):\n"
                "- If the user asks a specific question or requests a specific reasoning/extraction output (e.g., 'Calculate the ATS score of the resume', 'what can you do with this PDF?', 'extract all names', 'who is the author?'), this is NOT ambiguous. You MUST NOT ask a clarifying question. Choose type='tool_call' and run the appropriate tool immediately (usually `conversational_answer` for custom queries/extractions).\n"
                "- Do not clarify if there is no ambiguity. If the user's goal can be fulfilled by the tools or general synthesis, proceed immediately.\n\n"
                "Available Tools:\n"
                "- fetch_youtube_transcript: Fetch transcript for a YouTube URL. Args: {'url': str}\n"
                "- summarize_text: Summarize text content. Args: {'text': str}\n"
                "- analyze_sentiment: Sentiment analysis of text. Args: {'text': str}\n"
                "- explain_code: Explain code syntax, bug analysis, time complexity. Args: {'code': str}\n"
                "- conversational_answer: Use this for answering general questions, specific queries, information extraction, capabilities queries (e.g. 'what can you do'), or custom reasoning tasks (such as ATS score calculations, resume reviews, answering questions about document contents) that do not require specialized tools like summarization or sentiment. Args: {'query': str}\n\n"
                f"{history_context}"
                f"User Original Query: {query}\n\n"
                f"Files Context:\n{file_context}\n\n"
                f"Previous Execution Steps:\n{json.dumps(history, indent=2)}\n\n"
                "Decide the next action. Choose 'clarify' (to ask a question), 'tool_call' (to invoke tools), "
                "or 'finish' (if you have all analytical results needed to synthesize the final answer)."
            )
            
            cost_tracker.add_text_input(planner_prompt)
            
            try:
                # Call structured planning step via unified LLM gateway
                res_text = llm.generate_text(
                    prompt=planner_prompt,
                    system_instruction="You are a structured AI agent coordinator.",
                    json_schema=AgentPlanModel,
                    suite=suite,
                    model_name=model_name
                )
                
                cost_tracker.add_text_output(res_text)
                plan = json.loads(res_text)
                
                logger.info(f"Planned step result: {plan}")
                
                # Record trace step
                trace.append({
                    "step": step_idx,
                    "reasoning": plan.get("reasoning", ""),
                    "type": plan.get("type", "finish"),
                    "details": plan.get("question") if plan.get("type") == "clarify" else plan.get("tool_calls")
                })
                
                if plan["type"] == "clarify":
                    clarifying_question = plan.get("question")
                    break
                    
                elif plan["type"] == "finish":
                    break
                    
                elif plan["type"] == "tool_call":
                    tool_calls = plan.get("tool_calls", [])
                    if not tool_calls:
                        logger.warning("Empty tool calls list returned. Forcing finish.")
                        break
                        
                    step_results = []
                    for tc in tool_calls:
                        tool_name = tc.get("tool")
                        tool_args = tc.get("args", {})
                        
                        logger.info(f"Executing tool {tool_name} with args {tool_args}")
                        
                        try:
                            # Invoke tool
                            if tool_name == "fetch_youtube_transcript":
                                res = tools.fetch_youtube_transcript(tool_args.get("url", ""))
                            elif tool_name == "summarize_text":
                                res = tools.summarize_text(tool_args.get("text", ""), suite, model_name)
                            elif tool_name == "analyze_sentiment":
                                res = tools.analyze_sentiment(tool_args.get("text", ""), suite, model_name)
                            elif tool_name == "explain_code":
                                res = tools.explain_code(tool_args.get("code", ""), suite, model_name)
                            elif tool_name == "conversational_answer":
                                res = {"response": tool_args.get("query", "")}
                            else:
                                res = {"error": f"Unknown tool: {tool_name}"}
                        except Exception as tool_ex:
                            logger.error(f"Tool {tool_name} failed: {tool_ex}")
                            res = {"error": f"Tool execution failed: {str(tool_ex)}"}
                            
                        step_results.append({
                            "tool": tool_name,
                            "args": tool_args,
                            "output": res
                        })
                        
                    history.append({
                        "step": step_idx,
                        "results": step_results
                    })
                    
            except Exception as plan_err:
                logger.error(f"Planning step failed: {plan_err}", exc_info=True)
                trace.append({
                    "step": step_idx,
                    "reasoning": "Planner failed to execute.",
                    "type": "finish",
                    "details": f"Error: {str(plan_err)}"
                })
                break
                
        # 3. Synthesize response
        if clarifying_question:
            final_answer = clarifying_question
        else:
            logger.info("Synthesizing final response...")
            synthesis_prompt = (
                "You are an expert synthesizer. Combine the user's original query, the extracted file content, "
                "and the tool execution history to answer the query completely. "
                "Provide a direct, helpful, and high-quality final response.\n\n"
                "Instructions:\n"
                "- Output must be text-only (markdown is allowed).\n"
                "- Do not mention internal tool names (e.g. fetch_youtube_transcript) in your text response. Instead, "
                "describe what was fetched naturally (e.g., 'Retrieved the YouTube transcript for...').\n"
                "- Be concise and format summaries or code explanations nicely if requested.\n\n"
                f"{history_context}"
                f"User Original Query: {query}\n\n"
                f"Files Context:\n{file_context}\n\n"
                f"Tool Execution History:\n{json.dumps(history, indent=2)}"
            )
            
            cost_tracker.add_text_input(synthesis_prompt)
            
            try:
                res_text = llm.generate_text(
                    prompt=synthesis_prompt,
                    system_instruction="You are a helpful synthesizer compiling final results.",
                    suite=suite,
                    model_name=model_name
                )
                cost_tracker.add_text_output(res_text)
                final_answer = res_text.strip()
            except Exception as synth_err:
                logger.error(f"Synthesis failed: {synth_err}")
                final_answer = f"Error generating final response: {str(synth_err)}"
                
        return {
            "output": final_answer,
            "trace": trace,
            "extracted_content": extracted_content,
            "cost": cost_tracker.get_totals()
        }
