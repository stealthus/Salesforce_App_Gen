/**
 * RFP Response Assistant - Frontend Logic
 */

// Global state
const state = {
    fileKey: null,
    fileName: null,
    questions: [],
    responses: [],
    metadata: {},
    responseGuide: {},
    // No view toggle needed - only response structure view is used
};

// DOM elements
let elements = {};

// API endpoints
const api = {
    upload: '/api/upload',
    extract: '/api/extract-questions',
    generate: '/api/generate',
    chat: '/api/chat',
    reset: '/api/reset',
    questions: (fileKey) => `/api/questions/${fileKey}`,
    metadata: (fileKey) => `/api/metadata/${fileKey}`,
    responseGuide: (fileKey) => `/api/response-guide/${fileKey}`,
    export: '/api/export',
    cacheResponse: '/api/cache-response',
    createQuestion: '/api/create-question',
    createFinalResponse: '/api/create-final-response',
    download: (fileKey, filename) => `/api/download/${fileKey}/${filename}`,
    getFileKey: () => {
        // Get file key from state, URL, or other sources
        if (state && state.fileKey) {
            return state.fileKey;
        }
        
        // Get from URL if available
        const urlParams = new URLSearchParams(window.location.search);
        const fileKeyFromUrl = urlParams.get('key');
        if (fileKeyFromUrl) {
            return fileKeyFromUrl;
        }
        
        // No file key found
        return '';
    }
};

// Initialize UI elements
function initUI() {
    console.log('Initializing UI elements');
    // Assign element references
    elements = {
        // Upload section elements
        uploadForm: document.getElementById('upload-form'),
        fileInput: document.getElementById('file-input'),
        uploadBtn: document.getElementById('upload-btn'),
        dropArea: document.getElementById('drop-area'),
        uploadProgress: document.getElementById('upload-progress'),
        progressFill: document.querySelector('.progress-fill'),
        progressText: document.getElementById('progress-text'),
        
        // Section containers
        uploadSection: document.getElementById('upload-section'),
        questionsSection: document.getElementById('questions-section'),
        responsesSection: document.getElementById('responses-section'),
        exportSection: document.getElementById('export-section'),
        
        // Navigation buttons
        generateAllBtn: document.getElementById('generate-all-btn'),
        viewResponsesBtn: document.getElementById('view-responses-btn'),
        backToQuestionsBtn: document.getElementById('back-to-questions-btn'),
        backToResponsesBtn: document.getElementById('back-to-responses-btn'),
        exportBtn: document.getElementById('export-btn'),
        
        // Content containers
        metadataContent: document.getElementById('metadata-content'),
        responseGuideContent: document.getElementById('response-guide-content'),
        responsesList: document.getElementById('responses-list'),
        exportPreview: document.getElementById('export-preview'),
        downloadMdBtn: document.getElementById('download-md-btn'),
        
        // Chat elements
        chatToggle: document.getElementById('chat-toggle'),
        chatContainer: document.getElementById('chat-container'),
        chatClose: document.getElementById('chat-close'),
        chatInput: document.getElementById('chat-input'),
        chatSend: document.getElementById('chat-send'),
        chatMessages: document.getElementById('chat-messages'),
        
        // Templates
        questionTemplate: document.getElementById('question-template'),
        responseTemplate: document.getElementById('response-template'),
        chatMessageTemplate: document.getElementById('chat-message-template'),
        chatLoadingTemplate: document.getElementById('chat-loading-template'),
        
        // Response structure view
        responseStructure: document.getElementById('response-structure')
    };
    
    console.log('UI elements initialized', elements.fileInput ? 'File input found' : 'File input missing');
}

// Initialize the application
function init() {
    console.log('Initializing application');
    // First initialize UI elements
    initUI();
    // Then set up event listeners
    setupEventListeners();
    // Initialize chat functionality
    initChat();
    console.log('Application initialized successfully');
}

// Set up event listeners
function setupEventListeners() {
    // File upload events
    elements.dropArea.addEventListener('dragover', handleDragOver);
    elements.dropArea.addEventListener('dragleave', handleDragLeave);
    elements.dropArea.addEventListener('drop', handleDrop);
    elements.fileInput.addEventListener('change', handleFileSelect);
    elements.dropArea.addEventListener('click', () => elements.fileInput.click());
    
    // Navigation events
    elements.generateAllBtn.addEventListener('click', handleGenerateAll);
    elements.viewResponsesBtn.addEventListener('click', showResponsesSection); // New button for viewing responses
    elements.backToQuestionsBtn.addEventListener('click', showQuestionsSection);
    elements.exportBtn.addEventListener('click', handleExport);
    elements.backToResponsesBtn.addEventListener('click', showResponsesSection);
    elements.downloadMdBtn.addEventListener('click', handleDownload);
    
    // Since we've removed the view toggle functionality, we add the final response button
    // This adds a button that allows users to generate the comprehensive final response
    setTimeout(() => {
        addCreateFinalResponseButton();
    }, 1000); // Slight delay to ensure all DOM elements are fully loaded
}

// File upload handlers
function handleDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
    elements.dropArea.classList.add('drag-over');
}

function handleDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    elements.dropArea.classList.remove('drag-over');
}

function handleDrop(e) {
    console.log('File dropped');
    e.preventDefault();
    e.stopPropagation();
    elements.dropArea.classList.remove('drag-over');
    
    const file = e.dataTransfer.files[0];
    console.log('Dropped file:', file ? file.name : 'No file');
    
    if (file && (file.type === 'application/pdf' || file.type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')) {
        console.log('Valid file type, starting upload process');
        uploadFile(file);
    } else {
        console.warn('Invalid file type:', file ? file.type : 'No file');
        alert('Please upload a PDF or DOCX file');
    }
}

function handleFileSelect(e) {
    console.log('File selected via input');
    const file = e.target.files[0];
    console.log('Selected file:', file ? file.name : 'No file');
    
    if (file && (file.type === 'application/pdf' || file.type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')) {
        console.log('Valid file type, starting upload process');
        uploadFile(file);
    } else {
        console.warn('Invalid file type:', file ? file.type : 'No file');
        alert('Please upload a PDF or DOCX file');
    }
}

// Validate file type for upload
function isValidFileType(file) {
    const validTypes = ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'];
    return validTypes.includes(file.type);
}

// Upload file to server
async function uploadFile(file) {
    console.log('Uploading file:', file.name);
    
    // Reset the UI state
    elements.uploadProgress.style.display = 'block';
    elements.progressFill.style.width = '10%';
    elements.progressText.textContent = 'Uploading document...';
    
    try {
        // Create form data
        const formData = new FormData();
        formData.append('file', file);
        
        // Send the file to the server
        const response = await fetch(api.upload, {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            throw new Error(`Server error: ${response.status} ${response.statusText}`);
        }
        
        // Update progress
        elements.progressFill.style.width = '50%';
        elements.progressText.textContent = 'Processing document...';
        
        // Parse response
        const data = await response.json();
        if (!data || !data.file_id) {
            throw new Error('Invalid response: missing file ID');
        }
        
        // Update state
        state.fileKey = data.file_id;
        state.fileName = data.filename || 'document';
        
        // Show completion
        elements.progressFill.style.width = '100%';
        elements.progressText.textContent = 'Document processed successfully!';
        
        // Fetch document data
        await fetchQuestions();
        await fetchMetadata();
        await fetchResponseGuide();
        
        // Render and show results
        setTimeout(() => {
            renderQuestions();
            renderMetadata();
            renderResponseGuide();
            showQuestionsSection();
        }, 1000);
        
    } catch (error) {
        console.error('Error uploading file:', error);
        
        // Show error in UI
        elements.progressFill.style.width = '100%';
        elements.progressFill.style.backgroundColor = 'var(--error-color)';
        elements.progressText.textContent = `Error: ${error.message}`;
        
        // Alert the user
        alert(`File upload failed: ${error.message}`);
    }
}

// Fetch questions from server
async function fetchQuestions() {
    try {
        const response = await fetch(api.questions(state.fileKey));
        if (!response.ok) {
            throw new Error('Failed to fetch questions');
        }
        
        const data = await response.json();
        state.questions = data.questions || [];
        console.log('Fetched questions:', state.questions);
    } catch (error) {
        console.error('Error fetching questions:', error);
    }
}

// Fetch metadata from server
async function fetchMetadata() {
    try {
        const response = await fetch(api.metadata(state.fileKey));
        if (!response.ok) {
            throw new Error('Failed to fetch metadata');
        }
        
        const data = await response.json();
        state.metadata = data.metadata || {};
        console.log('Fetched metadata:', state.metadata);
    } catch (error) {
        console.error('Error fetching metadata:', error);
    }
}

// Fetch response guide from server
async function fetchResponseGuide() {
    try {
        const response = await fetch(api.responseGuide(state.fileKey));
        if (!response.ok) {
            throw new Error('Failed to fetch response guide');
        }
        
        const data = await response.json();
        state.responseGuide = data.response_guide || {};
        console.log('Fetched response guide:', state.responseGuide);
    } catch (error) {
        console.error('Error fetching response guide:', error);
        if (elements.responseGuideContent) {
            elements.responseGuideContent.innerHTML = '<p>Error loading response guide</p>';
        }
    }
}

// Render questions content (only response structure view)
function renderQuestions() {
    // Always render the response structure view
    renderResponseStructure();
}

// renderQuestionsList function removed as we now only use response structure view

// Toggle function removed as we now only use response structure view

// Helper function to organize questions by section
function organizeQuestionsBySection() {
    // Sort questions so they appear in their proper sections
    state.questions.sort((a, b) => {
        // First compare by section name
        if (a.section < b.section) return -1;
        if (a.section > b.section) return 1;
        
        // Then by type (keeping strategic questions together)
        const aIsStrategic = a.type === 'Strategic' || a.original_text === 'STRATEGIC ADDITION';
        const bIsStrategic = b.type === 'Strategic' || b.original_text === 'STRATEGIC ADDITION';
        
        if (aIsStrategic && !bIsStrategic) return 1;
        if (!aIsStrategic && bIsStrategic) return -1;
        
        // Lastly by ID to maintain stable order
        return a.id < b.id ? -1 : 1;
    });
}

// Custom question creation function
async function createCustomQuestion(sectionName) {
    const questionText = prompt(`Create a new question for "${sectionName}" section:`, "");
    
    if (!questionText || questionText.trim() === '') {
        return; // User cancelled or entered empty text
    }
    
    console.log(`Creating custom question for section: ${sectionName}`);
    try {
        const response = await fetch(api.createQuestion, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                file_key: state.fileKey,
                section: sectionName,
                text: questionText
            })
        });
        
        if (!response.ok) {
            throw new Error(`Server returned ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        console.log('Created custom question:', data.question);
        
        // Make sure the question has proper section information
        if (data.question) {
            data.question.section = sectionName;
            data.question.response_section = sectionName;
            
            // Add to state
            state.questions.push(data.question);
            
            // Re-organize questions by section for proper display
            organizeQuestionsBySection();
            renderQuestions();
            
            // Scroll to the newly created question after a short delay
            setTimeout(() => {
                const questionElement = document.querySelector(`.question-item[data-question-id="${data.question.id}"]`);
                if (questionElement) {
                    questionElement.scrollIntoView({ behavior: 'smooth' });
                    questionElement.classList.add('highlight-new');
                    setTimeout(() => questionElement.classList.remove('highlight-new'), 3000);
                }
            }, 100);
        }
    } catch (error) {
        console.error('Error creating custom question:', error);
        alert(`Error creating question: ${error.message}`);
    }
}

// Handle final response generation
async function handleCreateFinalResponse() {
    // Check if we have a file key
    if (!state.fileKey) {
        alert('Please upload a document first');
        return;
    }
    
    console.log('Creating final response document');
    try {
        // Show loading state
        const btn = document.getElementById('create-final-response-btn');
        if (!btn) {
            throw new Error('Create final response button not found');
        }
        
        const originalText = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating...';
        btn.disabled = true;
        
        // Get the file key using our helper
        const effectiveFileKey = api.getFileKey();
        console.log('Using file key for final response:', effectiveFileKey);
        
        if (!effectiveFileKey) {
            throw new Error('No file key found. Please upload a document first.');
        }
        
        // Call API with the file key we found
        const response = await fetch(api.createFinalResponse, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ file_key: effectiveFileKey })
        });
        
        if (!response.ok) {
            throw new Error(`Server returned ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        console.log('Final response created:', data);
        
        // Success message
        alert('Final response document created successfully!');
        
        // Add download button
        const downloadLink = document.createElement('a');
        downloadLink.href = api.download(effectiveFileKey, 'final_response.md');
        downloadLink.download = 'final_response.md';
        downloadLink.className = 'button secondary';
        downloadLink.innerHTML = '<i class="fas fa-download"></i> Download Final Response';
        downloadLink.onclick = () => {
            console.log('Downloading from:', downloadLink.href);
        };
        
        // Add to UI
        const actionsContainer = btn.parentElement;
        actionsContainer.appendChild(downloadLink);
        
        // Reset button
        btn.innerHTML = originalText;
        btn.disabled = false;
        
    } catch (error) {
        console.error('Error creating final response:', error);
        
        // Display a friendlier message if no responses found
        const errorMessage = error.message.includes('No responses found') ?
            "No responses have been generated yet. The document structure has been created, but for a complete document, generate individual responses first." :
            `Error creating final response: ${error.message}`;
        
        // Simply show as a message, not an error since the operation still completes
        alert(errorMessage);
        
        // Reset button if it exists
        const btn = document.getElementById('create-final-response-btn');
        if (btn) {
            btn.innerHTML = 'Create Final Response';
            btn.disabled = false;
        }
    }
}

// Add Create Final Response button to the UI
function addCreateFinalResponseButton() {
    // Create the button element
    const btn = document.createElement('button');
    btn.id = 'create-final-response-btn';
    btn.className = 'button primary';
    btn.innerHTML = '<i class="fas fa-file-alt"></i> Create Final Response';
    btn.onclick = handleCreateFinalResponse;
    
    // Add to appropriate place in UI
    const container = document.createElement('div');
    container.className = 'response-actions';
    container.appendChild(btn);
    
    // Insert after response guide box
    const responseGuideBox = document.getElementById('response-guide-box');
    if (responseGuideBox && responseGuideBox.parentNode) {
        responseGuideBox.parentNode.insertBefore(container, responseGuideBox.nextSibling);
    } else {
        // Fallback - add to response guide content
        const responseGuideContent = document.getElementById('response-guide-content');
        if (responseGuideContent) {
            responseGuideContent.appendChild(container);
        }
    }
}

// Render the response structure view
function renderResponseStructure() {
    if (!elements.responseStructure) return;
    
    // Clear the response structure container
    elements.responseStructure.innerHTML = '';
    
    if (!state.responseGuide || !state.questions || state.questions.length === 0) {
        elements.responseStructure.innerHTML = '<p>No response structure available.</p>';
        return;
    }
    
    // Get all response sections from questions
    const sections = {};
    state.questions.forEach(question => {
        if (question.response_section) {
            if (!sections[question.response_section]) {
                sections[question.response_section] = {
                    title: question.response_section,
                    questions: [],
                    requirementCount: 0,
                    strategicCount: 0
                };
            }
            
            // Track question type
            const isStrategic = question.type === 'Strategic' || question.original_text === 'STRATEGIC ADDITION';
            if (isStrategic) {
                sections[question.response_section].strategicCount++;
            } else {
                sections[question.response_section].requirementCount++;
            }
            
            // Add question to section
            sections[question.response_section].questions.push(question);
        }
    });
    
    // If response guide has submission_structure, use it to order sections
    let orderedSections = [];
    if (state.responseGuide.submission_structure && Array.isArray(state.responseGuide.submission_structure)) {
        // Extract section names from response guide
        const guideStructure = state.responseGuide.submission_structure.map(item => {
            if (typeof item === 'object' && item.section) {
                return item.section;
            } else if (typeof item === 'string') {
                return item;
            }
            return null;
        }).filter(item => item !== null);
        
        // First add sections that match the guide structure
        guideStructure.forEach(sectionName => {
            if (sections[sectionName]) {
                orderedSections.push(sections[sectionName]);
                delete sections[sectionName];
            } else {
                // Create empty section based on guide
                orderedSections.push({
                    title: sectionName,
                    questions: [],
                    requirementCount: 0,
                    strategicCount: 0,
                    isEmpty: true
                });
            }
        });
    }
    
    // Add any remaining sections not in the guide
    Object.values(sections).forEach(section => {
        orderedSections.push(section);
    });
    
    // Add executive summary section if it's not already included
    if (!orderedSections.find(s => s.title === 'Executive Summary')) {
        orderedSections.unshift({
            title: 'Executive Summary',
            questions: [],
            requirementCount: 0,
            strategicCount: 0,
            isEmpty: true
        });
    }
    
    // Render each section
    orderedSections.forEach(section => {
        // Create section header
        const sectionHeader = document.createElement('div');
        sectionHeader.className = 'section-header';
        
        // Add section title
        const sectionTitle = document.createElement('h3');
        sectionTitle.textContent = section.title;
        sectionHeader.appendChild(sectionTitle);
        
        // Add section metadata
        const sectionMeta = document.createElement('div');
        sectionMeta.className = 'section-meta';
        
        // Add counts
        const requirementCount = document.createElement('div');
        requirementCount.textContent = `${section.requirementCount} Requirements`;
        sectionMeta.appendChild(requirementCount);
        
        const strategicCount = document.createElement('div');
        strategicCount.textContent = `${section.strategicCount} Strategic Additions`;
        sectionMeta.appendChild(strategicCount);
        
        // Add section strength indicator
        const strengthContainer = document.createElement('div');
        strengthContainer.className = 'section-strength';
        
        const strengthLabel = document.createElement('span');
        strengthLabel.textContent = 'Section Strength:';
        strengthContainer.appendChild(strengthLabel);
        
        const strengthIndicator = document.createElement('div');
        strengthIndicator.className = 'section-strength-indicator';
        
        // Calculate section strength percentage based on number of questions and strategic additions
        const totalQuestions = section.requirementCount + section.strategicCount;
        const hasStrategic = section.strategicCount > 0;
        let strengthPercent = totalQuestions === 0 ? 0 : Math.min(100, (totalQuestions * 10) + (hasStrategic ? 30 : 0));
        
        const strengthFill = document.createElement('div');
        strengthFill.className = 'fill';
        strengthFill.style.width = `${strengthPercent}%`;
        strengthIndicator.appendChild(strengthFill);
        
        strengthContainer.appendChild(strengthIndicator);
        sectionMeta.appendChild(strengthContainer);
        
        sectionHeader.appendChild(sectionMeta);
        
        // Add section actions container
        const sectionActions = document.createElement('div');
        sectionActions.className = 'section-actions';
        
        // If section has no questions, add a create question button
        if (section.questions.length === 0) {
            const createQuestionBtn = document.createElement('button');
            createQuestionBtn.className = 'button secondary create-question-btn';
            createQuestionBtn.innerHTML = '<i class="fas fa-plus"></i> Create Question';
            createQuestionBtn.onclick = function() {
                createCustomQuestion(section.title);
            };
            sectionActions.appendChild(createQuestionBtn);
        }
        
        sectionHeader.appendChild(sectionActions);
        elements.responseStructure.appendChild(sectionHeader);
        
        // If section has questions, render them
        if (section.questions.length > 0) {
            const questionsList = document.createElement('div');
            questionsList.className = 'questions-list';
            
            // Sort questions: requirements first, then strategic additions
            const sortedQuestions = [...section.questions].sort((a, b) => {
                const aIsStrategic = a.type === 'Strategic' || a.original_text === 'STRATEGIC ADDITION';
                const bIsStrategic = b.type === 'Strategic' || b.original_text === 'STRATEGIC ADDITION';
                
                if (aIsStrategic && !bIsStrategic) return 1;
                if (!aIsStrategic && bIsStrategic) return -1;
                return 0;
            });
            
            // Add each question
            sortedQuestions.forEach(question => {
                const template = elements.questionTemplate.content.cloneNode(true);
                const questionItem = template.querySelector('.question-item');
                
                // Get the display text (prefer search_query, then original_text, then fall back to text)
                const displayText = question.search_query || question.original_text || question.text || 'No text available';
                
                // Set question text and section
                template.querySelector('.question-text').textContent = displayText;
                template.querySelector('.question-section').textContent = question.section || 'General';
                
                // Check if this is a strategic question
                const isStrategic = question.type === 'Strategic' || question.original_text === 'STRATEGIC ADDITION';
                if (isStrategic) {
                    questionItem.classList.add('strategic');
                    
                    // Add question type badge
                    const typeBadge = document.createElement('span');
                    typeBadge.className = 'question-type-badge strategic';
                    typeBadge.textContent = 'Strategic';
                    questionItem.appendChild(typeBadge);
                    
                    // Add differentiation potential if available
                    if (question.differentiation_potential) {
                        const diffIndicator = document.createElement('div');
                        diffIndicator.className = `differentiation-indicator ${question.differentiation_potential.toLowerCase()}`;
                        diffIndicator.innerHTML = `<i class="fas fa-star"></i> ${question.differentiation_potential} Differentiation Potential`;
                        template.querySelector('.question-details').appendChild(diffIndicator);
                    }
                } else {
                    // Add question type badge for requirements
                    const typeBadge = document.createElement('span');
                    typeBadge.className = 'question-type-badge requirement';
                    typeBadge.textContent = 'Requirement';
                    questionItem.appendChild(typeBadge);
                }
                
                // Add priority if available
                if (question.priority) {
                    const priorityBadge = document.createElement('span');
                    priorityBadge.className = `priority-badge ${question.priority.toLowerCase()}`;
                    priorityBadge.textContent = question.priority;
                    template.querySelector('.question-header').appendChild(priorityBadge);
                }
                
                // Add generate button event
                const generateBtn = template.querySelector('.generate-btn');
                generateBtn.addEventListener('click', () => handleGenerateResponse(question));
                
                // Add question to list
                questionItem.dataset.questionId = question.id;
                questionsList.appendChild(questionItem);
            });
            
            elements.responseStructure.appendChild(questionsList);
        } else if (section.isEmpty) {
            // For empty sections, show a message
            const emptyMessage = document.createElement('div');
            emptyMessage.className = 'empty-section-message';
            emptyMessage.innerHTML = `<p>No questions mapped to this section. Consider adding strategic content here.</p>`;
            elements.responseStructure.appendChild(emptyMessage);
        }
        
        // Add spacer
        const spacer = document.createElement('div');
        spacer.className = 'section-spacer';
        elements.responseStructure.appendChild(spacer);
    });
}

// Render metadata
function renderMetadata() {
    if (!state.metadata || Object.keys(state.metadata).length === 0) {
        elements.metadataContent.innerHTML = '<p>No metadata available for this document.</p>';
        return;
    }
    
    let html = '';
    
    // Add summary if available (our new high-level overview)
    if (state.metadata.summary) {
        html += '<div class="metadata-section executive-summary">';
        html += '<h4>Executive Summary</h4>';
        html += `<div class="metadata-item summary-section">
            <div class="metadata-value">${state.metadata.summary}</div>
        </div>`;
        html += '</div>'; // Close section
    }
    
    // Helper function to handle nested objects
    function getDisplayValue(value) {
        // Handle null/undefined
        if (value === null || value === undefined) {
            return '';
        }
        
        // If it's already a string, just return it
        if (typeof value === 'string') {
            return value;
        }
        
        // Handle objects carefully
        if (typeof value === 'object') {
            // For arrays
            if (Array.isArray(value)) {
                // Just display array items separated by commas
                return value.map(item => {
                    if (typeof item === 'object' && item !== null) {
                        // For objects inside arrays, try to get a readable representation
                        if (item.name || item.title || item.id) {
                            return item.name || item.title || item.id;
                        } else {
                            // Just get the values
                            return Object.values(item).join(', ');
                        }
                    }
                    return String(item);
                }).join(', ');
            } 
            // For regular objects
            else {
                // Special case for objects that might represent contact persons
                if (value.name) {
                    let displayStr = value.name;
                    if (value.role) displayStr += `, ${value.role}`;
                    if (value.email) displayStr += `, ${value.email}`;
                    return displayStr;
                }
                // If it has nested contact info, try to extract that
                else if (value.contact || value.email || value.phone) {
                    const parts = [];
                    if (value.contact) parts.push(value.contact);
                    if (value.email) parts.push(value.email);
                    if (value.phone) parts.push(value.phone);
                    return parts.join(', ');
                }
                // Otherwise, format the object in a more human-readable way
                else {
                    try {
                        // For objects with 1-3 properties, show key-value pairs
                        const entries = Object.entries(value);
                        if (entries.length <= 3) {
                            return entries.map(([k, v]) => `${k}: ${v}`).join(', ');
                        } else {
                            // For larger objects, just join values
                            return Object.values(value).join(', ');
                        }
                    } catch (e) {
                        // Fallback
                        return Object.values(value).join(', ');
                    }
                }
            }
        }
        
        // For any other type, convert to string
        return String(value);
    }
    
    // Add document information
    if (state.metadata.document) {
        html += '<div class="metadata-section">';
        html += '<h4>Document Information</h4>';
        if (typeof state.metadata.document === 'object' && state.metadata.document !== null) {
            for (const [key, value] of Object.entries(state.metadata.document)) {
                html += `<div class="metadata-item">
                    <div class="metadata-label">${key.replace(/_/g, ' ')}</div>
                    <div class="metadata-value">${getDisplayValue(value)}</div>
                </div>`;
            }
        } else {
            html += `<div class="metadata-item">
                <div class="metadata-value">${getDisplayValue(state.metadata.document)}</div>
            </div>`;
        }
        html += '</div>'; // Close section
    }
    
    // Add issuing organization
    if (state.metadata.issuing_organization) {
        html += '<div class="metadata-section">';
        html += '<h4>Issuing Organization</h4>';
        if (typeof state.metadata.issuing_organization === 'object' && state.metadata.issuing_organization !== null) {
            for (const [key, value] of Object.entries(state.metadata.issuing_organization)) {
                html += `<div class="metadata-item">
                    <div class="metadata-label">${key.replace(/_/g, ' ')}</div>
                    <div class="metadata-value">${getDisplayValue(value)}</div>
                </div>`;
            }
        } else {
            html += `<div class="metadata-item">
                <div class="metadata-value">${getDisplayValue(state.metadata.issuing_organization)}</div>
            </div>`;
        }
        html += '</div>'; // Close section
    }
    
    // Add key dates
    if (state.metadata.key_dates) {
        html += '<div class="metadata-section">';
        html += '<h4>Key Dates</h4>';
        if (Array.isArray(state.metadata.key_dates)) {
            for (const date of state.metadata.key_dates) {
                if (typeof date === 'object' && date !== null) {
                    if (date.name && date.date) {
                        html += `<div class="metadata-item">
                            <div class="metadata-label">${date.name}</div>
                            <div class="metadata-value">${getDisplayValue(date.date)}</div>
                        </div>`;
                    } else {
                        // Handle generic object
                        for (const [key, value] of Object.entries(date)) {
                            html += `<div class="metadata-item">
                                <div class="metadata-label">${key.replace(/_/g, ' ')}</div>
                                <div class="metadata-value">${getDisplayValue(value)}</div>
                            </div>`;
                        }
                    }
                } else {
                    html += `<div class="metadata-item">
                        <div class="metadata-value">${getDisplayValue(date)}</div>
                    </div>`;
                }
            }
        } else if (typeof state.metadata.key_dates === 'object' && state.metadata.key_dates !== null) {
            for (const [key, value] of Object.entries(state.metadata.key_dates)) {
                html += `<div class="metadata-item">
                    <div class="metadata-label">${key.replace(/_/g, ' ')}</div>
                    <div class="metadata-value">${getDisplayValue(value)}</div>
                </div>`;
            }
        } else {
            html += `<div class="metadata-item">
                <div class="metadata-value">${getDisplayValue(state.metadata.key_dates)}</div>
            </div>`;
        }
        html += '</div>'; // Close section
    }
    
    // Add other metadata
    for (const [key, value] of Object.entries(state.metadata)) {
        if (!['document', 'issuing_organization', 'key_dates', 'summary'].includes(key)) {
            html += '<div class="metadata-section">';
            html += `<h4 class="guide-heading"><strong>${key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}</strong></h4>`;
            
            if (Array.isArray(value)) {
                for (const item of value) {
                    if (typeof item === 'object' && item !== null) {
                        for (const [itemKey, itemValue] of Object.entries(item)) {
                            html += `<div class="metadata-item">
                                <div class="metadata-label">${itemKey.replace(/_/g, ' ')}</div>
                                <div class="metadata-value">${getDisplayValue(itemValue)}</div>
                            </div>`;
                        }
                    } else {
                        html += `<div class="metadata-item">
                            <div class="metadata-value">${getDisplayValue(item)}</div>
                        </div>`;
                    }
                }
            } else if (typeof value === 'object' && value !== null) {
                for (const [objKey, objValue] of Object.entries(value)) {
                    html += `<div class="metadata-item">
                        <div class="metadata-label">${objKey.replace(/_/g, ' ')}</div>
                        <div class="metadata-value">${getDisplayValue(objValue)}</div>
                    </div>`;
                }
            } else {
                html += `<div class="metadata-item">
                    <div class="metadata-value">${getDisplayValue(value)}</div>
                </div>`;
            }
            
            html += '</div>'; // Close section
        }
    }
    
    // Remove the last horizontal rule
    html = html.replace(/<hr>$/, '');
    
    elements.metadataContent.innerHTML = html;
}

// Render response guide
function renderResponseGuide() {
    const guide = state.responseGuide;
    let html = '';
    
    if (!guide || Object.keys(guide).length === 0) {
        elements.responseGuideContent.innerHTML = '<p>No response guide generated for this document.</p>';
        return;
    }
    
    // Add executive summary if available (our new high-level overview)
    if (guide.executive_summary) {
        html += '<h4 class="guide-heading"><strong>Executive Summary</strong></h4>';
        html += `<div class="metadata-item summary-section">
            <div class="metadata-value">${guide.executive_summary}</div>
        </div>`;
        html += '<hr>';
    }
    
    // Add submission structure
    if (guide.submission_structure) {
        html += '<h4 class="guide-heading"><strong>Submission Structure</strong></h4>';
        if (Array.isArray(guide.submission_structure)) {
            guide.submission_structure.forEach(section => {
                if (typeof section === 'object' && section !== null) {
                    // Get section name and description, handling possible null/undefined values
                    const sectionName = section.section || 'Section';
                    let sectionDesc = section.description || '';
                    
                    // Handle potential object description
                    if (typeof sectionDesc === 'object' && sectionDesc !== null) {
                        try {
                            sectionDesc = JSON.stringify(sectionDesc);
                        } catch (e) {
                            sectionDesc = 'Complex data structure';
                        }
                    }
                    
                    html += `<div class="metadata-item">
                        <div class="metadata-label">${sectionName}</div>
                        <div class="metadata-value">${sectionDesc}</div>
                    </div>`;
                    
                    if (section.requirements && Array.isArray(section.requirements)) {
                        html += '<ul>';
                        section.requirements.forEach(req => {
                            // Handle potential object requirement
                            let reqText = req;
                            if (typeof req === 'object' && req !== null) {
                                try {
                                    reqText = JSON.stringify(req);
                                } catch (e) {
                                    reqText = 'Complex requirement';
                                }
                            }
                            html += `<li>${reqText}</li>`;
                        });
                        html += '</ul>';
                    }
                } else {
                    html += `<div class="metadata-item">
                        <div class="metadata-value">${section}</div>
                    </div>`;
                }
            });
        }
        html += '<hr>';
    }
    
    // Add evaluation criteria
    if (guide.evaluation_criteria) {
        html += '<h4 class="guide-heading"><strong>Evaluation Criteria</strong></h4>';
        if (Array.isArray(guide.evaluation_criteria)) {
            guide.evaluation_criteria.forEach(item => {
                if (typeof item === 'object' && item !== null) {
                    for (const [key, value] of Object.entries(item)) {
                        // Handle nested objects to prevent [object Object] display
                        let displayValue = value;
                        if (typeof value === 'object' && value !== null) {
                            if (Array.isArray(value)) {
                                displayValue = value.join(', ');
                            } else {
                                try {
                                    displayValue = JSON.stringify(value);
                                } catch (e) {
                                    displayValue = 'Complex data structure';
                                }
                            }
                        }
                        
                        html += `<div class="metadata-item">
                            <div class="metadata-label">${key.replace(/_/g, ' ')}</div>
                            <div class="metadata-value">${displayValue}</div>
                        </div>`;
                    }
                } else {
                    html += `<div class="metadata-item">
                        <div class="metadata-value">${item}</div>
                    </div>`;
                }
            });
        } else if (typeof guide.evaluation_criteria === 'object' && guide.evaluation_criteria !== null) {
            for (const [key, value] of Object.entries(guide.evaluation_criteria)) {
                // Handle nested objects to prevent [object Object] display
                let displayValue = value;
                if (typeof value === 'object' && value !== null) {
                    if (Array.isArray(value)) {
                        displayValue = value.join(', ');
                    } else {
                        try {
                            displayValue = JSON.stringify(value);
                        } catch (e) {
                            displayValue = 'Complex data structure';
                        }
                    }
                }
                
                html += `<div class="metadata-item">
                    <div class="metadata-label">${key.replace(/_/g, ' ')}</div>
                    <div class="metadata-value">${displayValue}</div>
                </div>`;
            }
        } else {
            html += `<div class="metadata-item">
                <div class="metadata-value">${guide.evaluation_criteria}</div>
            </div>`;
        }
        html += '<hr>';
    }
    
    // Add compliance checklist
    if (guide.compliance_checklist) {
        html += '<h4 class="guide-heading"><strong>Compliance Checklist</strong></h4>';
        if (Array.isArray(guide.compliance_checklist)) {
            guide.compliance_checklist.forEach(item => {
                if (typeof item === 'object' && item !== null) {
                    for (const [key, value] of Object.entries(item)) {
                        // Handle nested objects to prevent [object Object] display
                        let displayValue = value;
                        if (typeof value === 'object' && value !== null) {
                            if (Array.isArray(value)) {
                                displayValue = value.join(', ');
                            } else {
                                try {
                                    displayValue = JSON.stringify(value);
                                } catch (e) {
                                    displayValue = 'Complex data structure';
                                }
                            }
                        }
                        
                        html += `<div class="metadata-item">
                            <div class="metadata-label">${key.replace(/_/g, ' ')}</div>
                            <div class="metadata-value">${displayValue}</div>
                        </div>`;
                    }
                } else {
                    html += `<div class="metadata-item">
                        <div class="metadata-value">${item}</div>
                    </div>`;
                }
            });
        } else if (typeof guide.compliance_checklist === 'object' && guide.compliance_checklist !== null) {
            for (const [key, value] of Object.entries(guide.compliance_checklist)) {
                // Handle nested objects to prevent [object Object] display
                let displayValue = value;
                if (typeof value === 'object' && value !== null) {
                    if (Array.isArray(value)) {
                        displayValue = value.join(', ');
                    } else {
                        try {
                            displayValue = JSON.stringify(value);
                        } catch (e) {
                            displayValue = 'Complex data structure';
                        }
                    }
                }
                
                html += `<div class="metadata-item">
                    <div class="metadata-label">${key.replace(/_/g, ' ')}</div>
                    <div class="metadata-value">${displayValue}</div>
                </div>`;
            }
        } else {
            html += `<div class="metadata-item">
                <div class="metadata-value">${guide.compliance_checklist}</div>
            </div>`;
        }
        html += '<hr>';
    }
    
    // Add other sections
    for (const [key, value] of Object.entries(guide)) {
        if (!['submission_structure', 'evaluation_criteria', 'compliance_checklist', 'executive_summary'].includes(key)) {
            html += `<h4 class="guide-heading"><strong>${key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}</strong></h4>`;
            
            if (Array.isArray(value)) {
                value.forEach(item => {
                    if (typeof item === 'object' && item !== null) {
                        for (const [itemKey, itemValue] of Object.entries(item)) {
                            // Handle nested objects or arrays to prevent [object Object] display
                            let displayValue = itemValue;
                            if (typeof itemValue === 'object' && itemValue !== null) {
                                if (Array.isArray(itemValue)) {
                                    displayValue = itemValue.join(', ');
                                } else {
                                    try {
                                        displayValue = JSON.stringify(itemValue);
                                    } catch (e) {
                                        displayValue = 'Complex data structure';
                                    }
                                }
                            }
                            
                            html += `<div class="metadata-item">
                                <div class="metadata-label">${itemKey.replace(/_/g, ' ')}</div>
                                <div class="metadata-value">${displayValue}</div>
                            </div>`;
                        }
                    } else {
                        html += `<div class="metadata-item">
                            <div class="metadata-value">${item}</div>
                        </div>`;
                    }
                });
            } else if (typeof value === 'object' && value !== null) {
                for (const [objKey, objValue] of Object.entries(value)) {
                    // Handle nested objects or arrays to prevent [object Object] display
                    let displayValue = objValue;
                    if (typeof objValue === 'object' && objValue !== null) {
                        if (Array.isArray(objValue)) {
                            displayValue = objValue.join(', ');
                        } else {
                            try {
                                displayValue = JSON.stringify(objValue);
                            } catch (e) {
                                displayValue = 'Complex data structure';
                            }
                        }
                    }
                    
                    html += `<div class="metadata-item">
                        <div class="metadata-label">${objKey.replace(/_/g, ' ')}</div>
                        <div class="metadata-value">${displayValue}</div>
                    </div>`;
                }
            } else {
                html += `<div class="metadata-item">
                    <div class="metadata-value">${value}</div>
                </div>`;
            }
            
            html += '<hr>';
        }
    }
    
    // Remove the last horizontal rule
    html = html.replace(/<hr>$/, '');
    
    elements.responseGuideContent.innerHTML = html;
}
async function handleGenerateResponse(question) {
    try {
        console.log('Starting response generation for question:', question);
        const questionItem = document.querySelector(`.question-item[data-question-id="${question.id}"]`);
        const generateBtn = questionItem.querySelector('.generate-btn');
        generateBtn.textContent = 'Generating...';
        generateBtn.disabled = true;
        
        // Remove any previous error messages
        const previousErrors = questionItem.querySelectorAll('.error-message');
        previousErrors.forEach(el => el.remove());
        
        // Prepare request data
        const requestData = {
            file_key: state.fileKey,
            questions: [question]
        };
        
        console.log('Sending request with data:', requestData);
        const response = await fetch(api.generate, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestData)
        });
        
        console.log('Response status:', response.status);
        if (!response.ok) {
            throw new Error(`Server returned ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        console.log('Response data:', data);
        
        // Get the first response (should only have one)
        const generatedResponse = data.responses && data.responses[0];
        if (!generatedResponse) {
            throw new Error('No response generated');
        }
        
        // Create a safe response object
        const safeResponse = {
            question_id: question.id,
            question_text: question.text || question.original_text || question.search_query || '',
            response_text: generatedResponse.response_text || 'No response text provided',
            sources: generatedResponse.sources || [],
            search_query: generatedResponse.search_query || '',
            system_prompt: generatedResponse.system_prompt || '',
            user_prompt: generatedResponse.user_prompt || '',
            knowledge_context: generatedResponse.knowledge_context || '',
            section: question.section || 'General'
        };
        
        console.log('Generated safe response object:', safeResponse);
        
        // Add to state
        state.responses.push(safeResponse);
        
        // Cache the response for later use in final response
        try {
            console.log('Caching response for future use');
            await fetch(api.cacheResponse, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    file_key: state.fileKey,
                    question_id: question.id,
                    response: safeResponse
                })
            });
            console.log('Response cached successfully');
        } catch (cacheError) {
            // Non-critical error - just log it
            console.warn('Failed to cache response, but UI will still work:', cacheError);
        }
        
        // Update button state
        generateBtn.textContent = 'Generated ✓';
        generateBtn.classList.add('success');
        
        // Show responses section after a short delay
        renderResponses();
        showResponsesSection();
        
    } catch (error) {
        console.error('Error generating response:', error);
        
        try {
            // Try to update the button state if possible
            const questionItem = document.querySelector(`.question-item[data-question-id="${question.id}"]`);
            if (questionItem) {
                const generateBtn = questionItem.querySelector('.generate-btn');
                if (generateBtn) {
                    generateBtn.textContent = 'Try Again';
                    generateBtn.classList.add('error');
                    generateBtn.disabled = false; // Enable the button so user can try again
                    
                    // Add error message
                    const errorMessage = document.createElement('div');
                    errorMessage.className = 'error-message';
                    errorMessage.textContent = `Error: ${error.message}`;
                    questionItem.appendChild(errorMessage);
                }
            }
        } catch (uiError) {
            // Even the error handling failed, log that too
            console.error('Error updating UI after failed response generation:', uiError);
        }
    }
}

// Generate responses for all questions
async function handleGenerateAll() {
    elements.generateAllBtn.textContent = 'Generating...';
    elements.generateAllBtn.disabled = true;
    
    try {
        // Generate responses for each question
        for (const question of state.questions) {
            await handleGenerateResponse(question);
        }
        
        // Update button state
        elements.generateAllBtn.textContent = 'All Generated ✓';
        elements.generateAllBtn.classList.add('success');
        
        // Show responses section after a short delay
        setTimeout(() => {
            renderResponses();
            showResponsesSection();
        }, 1000);
        
    } catch (error) {
        console.error('Error generating all responses:', error);
        elements.generateAllBtn.textContent = 'Error';
        elements.generateAllBtn.classList.add('error');
    }
}

// Render responses
function renderResponses() {
    console.log('Rendering responses:', state.responses);
    if (!elements.responsesList) {
        console.error('Response list element not found');
        return;
    }
    
    // Clear container
    elements.responsesList.innerHTML = '';
    
    // If no responses, show message
    if (state.responses.length === 0) {
        elements.responsesList.innerHTML = '<p>No responses generated yet.</p>';
        return;
    }
    
    // For each response
    state.responses.forEach(response => {
        // Find the matching question to get complete info
        const questionId = response.question_id;
        console.log('Looking for question with ID:', questionId);
        
        // Find the question object from state
        const question = state.questions.find(q => q.id === questionId);
        console.log('Found question:', question);
        
        // Create response item
        const responseItem = document.createElement('div');
        responseItem.className = 'response-item';
        responseItem.setAttribute('data-question-id', questionId);
        
        // Get question text from either question object or response
        const questionText = question ? 
            (question.text || question.original_text || question.search_query || 'Unknown Question') : 
            (response.question_text || 'No question text');
        
        // Create response header
        const responseHeader = document.createElement('h3');
        responseHeader.className = 'question-text';
        responseHeader.textContent = questionText;
        responseItem.appendChild(responseHeader);
        
        // Create response content
        const responseContent = document.createElement('div');
        responseContent.className = 'response-text';
        responseContent.innerHTML = formatMarkdown(response.response_text || 'No response available');
        responseItem.appendChild(responseContent);
        
        // Add section indicator if available
        if (question && question.section) {
            const sectionBadge = document.createElement('div');
            sectionBadge.className = 'section-badge';
            sectionBadge.textContent = question.section;
            responseHeader.appendChild(sectionBadge);
        }
        
        // Add debug information if available
        if (response.sources && response.sources.length > 0) {
            const debugInfo = document.createElement('div');
            debugInfo.className = 'debug-info';
            
            const debugToggle = document.createElement('button');
            debugToggle.className = 'debug-toggle';
            debugToggle.textContent = 'Show Sources';
            debugToggle.onclick = function() {
                const debugContent = this.nextElementSibling;
                if (debugContent.style.display === 'none') {
                    debugContent.style.display = 'block';
                    this.textContent = 'Hide Sources';
                } else {
                    debugContent.style.display = 'none';
                    this.textContent = 'Show Sources';
                }
            };
            debugInfo.appendChild(debugToggle);
            
            const debugContent = document.createElement('div');
            debugContent.className = 'debug-content';
            debugContent.style.display = 'none';
            
            // Add sources table
            const sourcesTable = document.createElement('table');
            sourcesTable.className = 'sources-table';
            
            // Add table header
            const tableHeader = document.createElement('thead');
            tableHeader.innerHTML = `
                <tr>
                    <th>Source</th>
                    <th>Relevance</th>
                    <th>Content</th>
                </tr>
            `;
            sourcesTable.appendChild(tableHeader);
            
            // Add table body
            const tableBody = document.createElement('tbody');
            response.sources.forEach(source => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${source.source || 'Unknown'}</td>
                    <td>${(source.score * 100).toFixed(1)}%</td>
                    <td>${source.text ? source.text.substring(0, 100) + '...' : 'No text'}</td>
                `;
                tableBody.appendChild(row);
            });
            sourcesTable.appendChild(tableBody);
            
            debugContent.appendChild(sourcesTable);
            debugInfo.appendChild(debugContent);
            responseItem.appendChild(debugInfo);
        }
        
        // Add to container
        elements.responsesList.appendChild(responseItem);
    });
}

// Handle export
function handleExport() {
    // Generate export preview
    let html = `<h1>${state.fileName || 'RFP Response'}</h1>\n\n`;
    
    state.responses.forEach(item => {
        html += `<h2>${item.question}</h2>\n<p>${item.response}</p>\n\n`;
    });
    
    // Set preview content
    elements.exportPreview.innerHTML = html;
    
    // Show export section
    showExportSection();
}

// Format markdown text for display
function formatMarkdown(text) {
    if (!text) return '';
    
    // Simple formatting: convert line breaks to <br>, bold and italics
    return text
        .replace(/\n/g, '<br>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        .replace(/^-\s(.+)$/gm, '<li>$1</li>')
        .replace(/<li>(.+)<\/li>/g, '<ul><li>$1</li></ul>');
}

// Handle download
function handleDownload() {
    // Generate markdown content
    let markdown = `# ${state.fileName || 'RFP Response'}\n\n`;
    
    state.responses.forEach(item => {
        markdown += `## ${item.question}\n\n${item.response}\n\n`;
    });
    
    // Create download link
    const blob = new Blob([markdown], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${state.fileName || 'rfp-response'}.md`;
    a.click();
    
    // Clean up
    URL.revokeObjectURL(url);
}

// Section navigation
function showQuestionsSection() {
    elements.uploadSection.classList.remove('active-section');
    elements.uploadSection.classList.add('hidden-section');
    
    elements.questionsSection.classList.remove('hidden-section');
    elements.questionsSection.classList.add('active-section');
    
    elements.responsesSection.classList.remove('active-section');
    elements.responsesSection.classList.add('hidden-section');
    
    elements.exportSection.classList.remove('active-section');
    elements.exportSection.classList.add('hidden-section');
}

function showResponsesSection() {
    elements.questionsSection.classList.remove('active-section');
    elements.questionsSection.classList.add('hidden-section');
    
    elements.responsesSection.classList.remove('hidden-section');
    elements.responsesSection.classList.add('active-section');
    
    elements.exportSection.classList.remove('active-section');
    elements.exportSection.classList.add('hidden-section');
}

function showExportSection() {
    elements.responsesSection.classList.remove('active-section');
    elements.responsesSection.classList.add('hidden-section');
    
    elements.exportSection.classList.remove('hidden-section');
    elements.exportSection.classList.add('active-section');
}

// Initialize the application
document.addEventListener('DOMContentLoaded', init);
