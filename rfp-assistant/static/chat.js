/**
 * RFP Response Assistant - Chat Functionality
 */

// Chat state
const chatState = {
    isOpen: false,
    messages: [],
    loading: false
};

// Initialize chat widget
function initChat() {
    // Get DOM elements
    const elements = {
        chatWidget: document.getElementById('chat-widget'),
        chatToggle: document.getElementById('chat-toggle'),
        chatContainer: document.getElementById('chat-container'),
        chatClose: document.getElementById('chat-close'),
        chatMessages: document.getElementById('chat-messages'),
        chatInput: document.getElementById('chat-input'),
        chatSend: document.getElementById('chat-send'),
        chatMessageTemplate: document.getElementById('chat-message-template'),
        chatLoadingTemplate: document.getElementById('chat-loading-template')
    };
    
    // API endpoint
    const chatAPI = '/api/chat'; // Make sure this exactly matches the endpoint in app.py

    // Event listeners for chat toggle
    elements.chatToggle.addEventListener('click', toggleChat);
    elements.chatClose.addEventListener('click', toggleChat);
    
    // Event listeners for sending messages
    elements.chatSend.addEventListener('click', sendChatMessage);
    elements.chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendChatMessage();
        }
    });
    
    // Event delegation for source toggles
    elements.chatMessages.addEventListener('click', (e) => {
        if (e.target.closest('.chat-sources-toggle')) {
            const sourcesList = e.target.closest('.chat-sources').querySelector('.chat-sources-list');
            sourcesList.classList.toggle('visible');
        }
    });
    
    console.log('Chat widget initialized');

    // Toggle chat open/closed
    function toggleChat() {
        chatState.isOpen = !chatState.isOpen;
        
        if (chatState.isOpen) {
            elements.chatContainer.classList.add('active');
            elements.chatInput.focus();
        } else {
            elements.chatContainer.classList.remove('active');
        }
    }

    // Send chat message to API
    async function sendChatMessage() {
        const message = elements.chatInput.value.trim();
        
        if (!message || chatState.loading) {
            return;
        }
        
        // Add user message to chat
        addChatMessage(message, 'user');
        
        // Clear input
        elements.chatInput.value = '';
        
        // Show loading indicator
        showChatLoading();
        chatState.loading = true;
        
        try {
            // Send message to API
            const response = await fetch(chatAPI, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ message })
            });
            
            if (!response.ok) {
                throw new Error(`Error: ${response.status}`);
            }
            
            const data = await response.json();
            
            // Remove loading indicator
            removeChatLoading();
            chatState.loading = false;
            
            // Add system response to chat
            if (data.response_text) {
                // Add the response with sources
                addChatMessage(data.response_text, 'system', data.sources);
            } else {
                addChatMessage('Sorry, I was unable to generate a response. Please try again.', 'system');
            }
        } catch (error) {
            console.error('Error sending chat message:', error);
            
            // Remove loading indicator
            removeChatLoading();
            chatState.loading = false;
            
            // Add error message
            addChatMessage('Sorry, there was an error processing your request. Please try again.', 'system');
        }
    }

    // Add message to chat
    function addChatMessage(text, type, sources = []) {
        // Clone template
        const template = elements.chatMessageTemplate.content.cloneNode(true);
        const messageElement = template.querySelector('.chat-message');
        
        // Add type class
        messageElement.classList.add(type);
        
        // Set message text
        messageElement.querySelector('.chat-text').textContent = text;
        
        // Handle sources if provided
        const sourcesContainer = messageElement.querySelector('.chat-sources');
        const sourcesList = messageElement.querySelector('.chat-sources-list');
        
        if (sources && sources.length > 0) {
            // Show sources toggle
            sourcesContainer.style.display = 'block';
            
            // Add sources to list
            sources.forEach(source => {
                const li = document.createElement('li');
                li.innerHTML = `<strong>${source.source || 'Unknown'}:</strong> ${source.text ? source.text.substring(0, 100) + '...' : 'No text available'}`;
                sourcesList.appendChild(li);
            });
        } else {
            // Hide sources section if no sources
            sourcesContainer.style.display = 'none';
        }
        
        // Add message to chat
        elements.chatMessages.appendChild(messageElement);
        
        // Scroll to bottom
        elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
        
        // Add to state
        chatState.messages.push({
            text,
            type,
            sources
        });
    }

    // Show loading indicator
    function showChatLoading() {
        const template = elements.chatLoadingTemplate.content.cloneNode(true);
        const loadingElement = template.querySelector('.chat-loading');
        loadingElement.id = 'current-loading';
        elements.chatMessages.appendChild(loadingElement);
        elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
    }

    // Remove loading indicator
    function removeChatLoading() {
        const loadingElement = document.getElementById('current-loading');
        if (loadingElement) {
            loadingElement.remove();
        }
    }
}

// Initialize chat when DOM is loaded
document.addEventListener('DOMContentLoaded', initChat);

// For debugging
console.log('Chat script loaded');

// Ensure the chat is initialized immediately if DOM is already loaded
if (document.readyState === 'complete' || document.readyState === 'interactive') {
    console.log('DOM already loaded, initializing chat');
    initChat();
}

// Global direct toggle function for the inline onclick handler
function toggleChatDirect() {
    console.log('Toggle chat clicked directly');
    const chatContainer = document.getElementById('chat-container');
    
    // Check if the chat container has the 'active' class
    const isActive = chatContainer.classList.contains('active');
    
    if (isActive) {
        chatContainer.classList.remove('active');
    } else {
        chatContainer.classList.add('active');
        document.getElementById('chat-input').focus();
    }
}
