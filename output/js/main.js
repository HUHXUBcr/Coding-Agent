const ARXIV_API_BASE = 'https://export.arxiv.org/api/query';
const CATEGORY_MAP = {
    'cs.AI': 'Artificial Intelligence',
    'cs.CL': 'Computation and Language',
    'cs.CC': 'Computational Complexity',
    'cs.CE': 'Computational Engineering, Finance, and Science',
    'cs.CG': 'Computational Geometry',
    'cs.GT': 'Computer Science and Game Theory',
    'cs.CV': 'Computer Vision and Pattern Recognition',
    'cs.CY': 'Computers and Society',
    'cs.CR': 'Cryptography and Security',
    'cs.DS': 'Data Structures and Algorithms',
    'cs.DB': 'Databases',
    'cs.DL': 'Digital Libraries',
    'cs.DM': 'Discrete Mathematics',
    'cs.DC': 'Distributed, Parallel, and Cluster Computing',
    'cs.ET': 'Emerging Technologies',
    'cs.FL': 'Formal Languages and Automata Theory',
    'cs.GL': 'General Literature',
    'cs.GR': 'Graphics',
    'cs.AR': 'Hardware Architecture',
    'cs.HC': 'Human-Computer Interaction',
    'cs.IR': 'Information Retrieval',
    'cs.IT': 'Information Theory',
    'cs.LG': 'Machine Learning',
    'cs.LO': 'Logic in Computer Science',
    'cs.MS': 'Mathematical Software',
    'cs.MA': 'Multiagent Systems',
    'cs.MM': 'Multimedia',
    'cs.NI': 'Networking and Internet Architecture',
    'cs.NE': 'Neural and Evolutionary Computing',
    'cs.NUM': 'Numerical Analysis',
    'cs.OS': 'Operating Systems',
    'cs.OH': 'Other',
    'cs.PF': 'Performance',
    'cs.PL': 'Programming Languages',
    'cs.RO': 'Robotics',
    'cs.SI': 'Social and Information Networks',
    'cs.SE': 'Software Engineering',
    'cs.SD': 'Sound',
    'cs.SC': 'Symbolic Computation',
    'cs.SY': 'Systems and Control'
};

let currentCategory = 'all';
let papersData = [];

document.addEventListener('DOMContentLoaded', () => {
    initializeCategoryNavigation();
    loadPapersForToday();
});

function initializeCategoryNavigation() {
    const navLinks = document.querySelectorAll('#category-nav a');
    if (!navLinks.length) return;
    
    // Add click event listeners to existing navigation links
    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const category = link.getAttribute('data-category');
            filterByCategory(category);
        });
    });
}

async function loadPapersForToday() {
    try {
        showLoadingIndicator(true);
        
        // Get today's date in YYYYMMDD format
        const today = new Date();
        const year = today.getFullYear();
        const month = String(today.getMonth() + 1).padStart(2, '0');
        const day = String(today.getDate()).padStart(2, '0');
        const dateString = `${year}${month}${day}`;
        
        console.log('Fetching papers for date:', dateString);
        
        // Build search query for recent papers
        const searchParams = new URLSearchParams({
            search_query: 'cat:cs.LG',
            sortBy: 'lastUpdatedDate',
            sortOrder: 'descending',
            max_results: 20
        });
        
        const apiUrl = `${ARXIV_API_BASE}?${searchParams}`;
        
        // Try multiple CORS proxies
        const proxies = [
            `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(apiUrl)}`,
            `https://corsproxy.io/?${encodeURIComponent(apiUrl)}`,
            `https://api.allorigins.win/raw?url=${encodeURIComponent(apiUrl)}`
        ];
        
        let data;
        let lastError;
        
        // Try each proxy in sequence
        for (let i = 0; i < proxies.length; i++) {
            const proxyUrl = proxies[i];
            console.log(`Trying proxy ${i + 1}:`, proxyUrl);
            
            try {
                const response = await fetch(proxyUrl, {
                    headers: {
                        'Accept': 'application/xml'
                    }
                });
                console.log(`Proxy ${i + 1} response status:`, response.status);
                
                if (response.ok) {
                    data = await response.text();
                    console.log('Response data length:', data.length);
                    console.log('First 200 chars of response:', data.substring(0, 200));
                    break; // Success, break out of loop
                } else {
                    lastError = new Error(`Proxy ${i + 1} failed with status ${response.status}`);
                }
            } catch (error) {
                console.error(`Proxy ${i + 1} error:`, error);
                lastError = error;
            }
        }
        
        // If all proxies failed, use sample data
        if (!data) {
            console.log('All proxies failed, using sample data');
            papersData = await getSamplePapers();
            renderPaperList(papersData);
            showError('Using sample data: API proxies unavailable');
            return;
        }
        
        papersData = parseArxivResponse(data);
        console.log('Parsed papers count:', papersData.length);
        
        renderPaperList(papersData);
    } catch (error) {
        console.error('Error loading papers:', error);
        console.error('Error details:', error.message);
        
        // Fallback: use sample data if API fails
        console.log('Using fallback sample data');
        papersData = await getSamplePapers();
        renderPaperList(papersData);
        
        showError(`Using sample data: ${error.message}`);
    } finally {
        showLoadingIndicator(false);
    }
}

function parseArxivResponse(xmlText) {
    const parser = new DOMParser();
    const xmlDoc = parser.parseFromString(xmlText, 'text/xml');
    
    const entries = xmlDoc.querySelectorAll('entry');
    const papers = [];
    
    entries.forEach(entry => {
        const id = entry.querySelector('id')?.textContent.split('/').pop() || '';
        const title = entry.querySelector('title')?.textContent.trim() || '';
        const published = entry.querySelector('published')?.textContent || '';
        const updated = entry.querySelector('updated')?.textContent || '';
        const summary = entry.querySelector('summary')?.textContent.trim() || '';
        
        // Extract categories
        const categories = Array.from(entry.querySelectorAll('category'))
            .map(cat => cat.getAttribute('term'))
            .filter(term => term.startsWith('cs.'));
            
        // Extract authors
        const authors = Array.from(entry.querySelectorAll('author')).map(author => ({
            name: author.querySelector('name')?.textContent || '',
            affiliation: '' // arXiv API doesn't provide affiliations directly
        }));
        
        // Extract PDF link
        const pdfLink = entry.querySelector('link[title="pdf"]')?.getAttribute('href') || '';
        
        papers.push({
            id,
            title,
            published,
            updated,
            summary,
            categories,
            authors,
            pdfLink
        });
    });
    
    return papers;
}

function renderPaperList(papers) {
    const container = document.getElementById('papers-container');
    if (!container) return;
    
    // Filter by current category if not 'all'
    const filteredPapers = currentCategory === 'all' 
        ? papers 
        : papers.filter(paper => paper.categories.includes(currentCategory));
    
    if (filteredPapers.length === 0) {
        container.innerHTML = '<p class="no-papers">No papers found for this category recently.</p>';
        return;
    }
    
    // Sort by submission time (newest first)
    filteredPapers.sort((a, b) => new Date(b.published) - new Date(a.published));
    
    container.innerHTML = filteredPapers.map(paper => `
        <div class="paper-item">
            <h3 class="paper-title"><a href="paper.html?id=${encodeURIComponent(paper.id)}">${escapeHtml(paper.title)}</a></h3>
            <div class="paper-meta">
                <span class="submission-time">${formatDateTime(paper.published)}</span>
                <span class="categories">${paper.categories.map(cat => 
                    `<span class="paper-field">${cat}</span>`
                ).join('')}</span>
            </div>
        </div>
    `).join('');
}

function filterByCategory(category) {
    currentCategory = category;
    
    // Update active link state
    const navLinks = document.querySelectorAll('#category-nav a');
    navLinks.forEach(link => {
        link.classList.remove('active');
        if (link.getAttribute('data-category') === category) {
            link.classList.add('active');
        }
    });
    
    renderPaperList(papersData);
}

function formatDateTime(dateString) {
    const date = new Date(dateString);
    return date.toLocaleTimeString([], { 
        hour: '2-digit', 
        minute: '2-digit',
        month: 'short',
        day: 'numeric'
    });
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

function showLoadingIndicator(show) {
    const loader = document.getElementById('loading-indicator');
    if (loader) {
        loader.style.display = show ? 'block' : 'none';
    }
}

function showError(message) {
    const container = document.getElementById('papers-container');
    if (container) {
        container.innerHTML = `<p class="error-message">${escapeHtml(message)}</p>`;
    }
}

async function getSamplePapers() {
    try {
        const response = await fetch('data/sample-papers.json');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        
        // Convert the JSON structure to match the expected format
        const samplePapers = Object.values(data.samplePapers).map(paper => ({
            id: paper.id,
            title: paper.title,
            published: new Date(paper.published).toISOString(),
            updated: new Date(paper.published).toISOString(),
            summary: paper.summary,
            categories: paper.categories,
            authors: paper.authors.map(name => ({ name, affiliation: '' })),
            pdfLink: paper.pdfLink
        }));
        
        return samplePapers;
    } catch (error) {
        console.error('Error loading sample papers:', error);
        // Fallback to hardcoded sample data if JSON loading fails
        return [
            {
                id: '2401.12345',
                title: 'Sample Paper: Advances in Machine Learning',
                published: '2024-01-01T00:00:00Z',
                updated: '2024-01-01T00:00:00Z',
                summary: 'This is a sample paper demonstrating the capabilities of the arXiv CS Daily application.',
                categories: ['cs.LG', 'cs.AI'],
                authors: [
                    { name: 'John Doe', affiliation: 'University of Example' },
                    { name: 'Jane Smith', affiliation: 'Tech Institute' }
                ],
                pdfLink: 'https://arxiv.org/pdf/2401.12345.pdf'
            }
        ];
    }
}