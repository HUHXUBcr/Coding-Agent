document.addEventListener('DOMContentLoaded', () => {
    const urlParams = new URLSearchParams(window.location.search);
    const paperId = urlParams.get('id');
    
    if (!paperId) {
        document.getElementById('paper-detail').innerHTML = '<p>Paper ID not provided.</p>';
        return;
    }
    
    fetchPaperDetails(paperId);
});

async function fetchPaperDetails(id) {
    try {
        const apiUrl = `https://export.arxiv.org/api/query?id_list=${id}`;
        console.log('Fetching paper details for ID:', id);
        console.log('API URL:', apiUrl);
        
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
                    method: 'GET',
                    headers: {
                        'Accept': 'application/xml',
                        'User-Agent': 'arXiv-CS-Daily/1.0'
                    },
                    timeout: 10000
                });
                
                console.log(`Proxy ${i + 1} response status:`, response.status);
                console.log(`Proxy ${i + 1} response headers:`, response.headers);
                
                if (response.ok) {
                    data = await response.text();
                    console.log('Response data length:', data.length);
                    console.log('First 500 chars of response:', data.substring(0, 500));
                    
                    if (data.includes('Error') || data.includes('error')) {
                        console.log('Response contains error, trying next proxy');
                        continue;
                    }
                    
                    break; 
                } else {
                    lastError = new Error(`Proxy ${i + 1} failed with status ${response.status}`);
                    console.log(`Proxy ${i + 1} failed:`, response.status, response.statusText);
                }
            } catch (error) {
                console.error(`Proxy ${i + 1} error:`, error);
                lastError = error;
            }
        }
        
        // If all proxies failed, use sample data
        if (!data) {
            console.log('All proxies failed, last error:', lastError);
            console.log('Using sample data');
            await displaySamplePaperDetails(id);
            return;
        }
        
        const parser = new DOMParser();
        const xmlDoc = parser.parseFromString(data, "text/xml");
        
        const parseError = xmlDoc.getElementsByTagName('parsererror');
        if (parseError.length > 0) {
            console.error('XML parsing error:', parseError[0].textContent);
            throw new Error('Invalid XML response');
        }
        
        const entry = xmlDoc.getElementsByTagName('entry')[0];
        
        if (!entry) {
            console.error('No entry found in response');
            throw new Error('Paper not found in API response');
        }
        
        const title = entry.getElementsByTagName('title')[0]?.textContent || 'No title';
        const authors = Array.from(entry.getElementsByTagName('author')).map(author => 
            author.getElementsByTagName('name')[0]?.textContent || 'Unknown author'
        );
        const published = entry.getElementsByTagName('published')[0]?.textContent || 'Unknown date';
        const summary = entry.getElementsByTagName('summary')[0]?.textContent || 'No summary available';
        
        let pdfLink = '';
        const links = entry.getElementsByTagName('link');
        for (let link of links) {
            if (link.getAttribute('title') === 'pdf' || link.getAttribute('type') === 'application/pdf') {
                pdfLink = link.getAttribute('href');
                break;
            }
        }
        
        if (!pdfLink) {
            pdfLink = `https://arxiv.org/pdf/${id}.pdf`;
        }
        
        console.log('Successfully parsed paper details:', { title, authors: authors.length, published });
        
        displayPaperDetails({
            id,
            title,
            authors,
            published: new Date(published).toLocaleDateString(),
            summary,
            pdfLink
        });
        
        setupCitationButtons(id, title, authors, published);
    } catch (error) {
        console.error('Error loading paper details:', error);
        
        console.log('Using fallback sample data due to error');
        await displaySamplePaperDetails(id);
    }
}

function displayPaperDetails(paper) {
    const detailContainer = document.getElementById('paper-detail');
    detailContainer.innerHTML = `
        <h2>${paper.title}</h2>
        <p><strong>Authors:</strong> ${paper.authors.join(', ')}</p>
        <p><strong>Published:</strong> ${paper.published}</p>
        <p>${paper.summary}</p>
        <a href="${paper.pdfLink}" target="_blank" class="btn">View PDF</a>
        <div class="citation-tools">
            <h3>Cite this paper</h3>
            <button id="bibtex-btn" class="btn">Copy BibTeX</button>
            <button id="citation-btn" class="btn">Copy Citation</button>
        </div>
    `;
}

async function displaySamplePaperDetails(id) {
    let paper;
    
    try {
        const response = await fetch('data/sample-papers.json');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        
        // Try to find the specific paper by ID
        if (data.samplePapers[id]) {
            paper = {
                title: data.samplePapers[id].title,
                authors: data.samplePapers[id].authors,
                published: data.samplePapers[id].published,
                summary: data.samplePapers[id].summary,
                pdfLink: data.samplePapers[id].pdfLink
            };
        } else {
            // Use default sample paper if specific ID not found
            paper = {
                title: data.defaultSamplePaper.title,
                authors: data.defaultSamplePaper.authors,
                published: data.defaultSamplePaper.published,
                summary: data.defaultSamplePaper.summary,
                pdfLink: data.defaultSamplePaper.pdfLink
            };
        }
    } catch (error) {
        console.error('Error loading sample papers:', error);
        // Fallback to hardcoded sample data if JSON loading fails
        const hardcodedSamplePapers = {
            '2401.12345': {
                title: 'Sample Paper: Advances in Machine Learning',
                authors: ['John Doe', 'Jane Smith'],
                published: 'January 1, 2024',
                summary: 'This is a sample paper demonstrating the capabilities of the arXiv CS Daily application. It showcases recent advances in machine learning algorithms and their practical applications.',
                pdfLink: 'https://arxiv.org/pdf/2401.12345.pdf'
            },
            '2401.12346': {
                title: 'Sample Paper: Computer Vision Applications',
                authors: ['Alice Johnson'],
                published: 'January 1, 2024',
                summary: 'Exploring recent developments in computer vision and image recognition. This paper discusses novel approaches to object detection and image classification.',
                pdfLink: 'https://arxiv.org/pdf/2401.12346.pdf'
            },
            '2401.12347': {
                title: 'Sample Paper: Natural Language Processing Trends',
                authors: ['Bob Wilson', 'Carol Brown'],
                published: 'January 1, 2024',
                summary: 'Analysis of current trends in natural language processing and text understanding. This research focuses on transformer architectures and their applications.',
                pdfLink: 'https://arxiv.org/pdf/2401.12347.pdf'
            }
        };
        
        paper = hardcodedSamplePapers[id] || {
            title: 'Sample Paper',
            authors: ['Sample Author'],
            published: '2024',
            summary: 'This is a sample paper demonstrating the arXiv CS Daily application functionality.',
            pdfLink: 'https://arxiv.org/abs/2401.00001'
        };
    }
    
    const detailContainer = document.getElementById('paper-detail');
    detailContainer.innerHTML = `
        <h2>${paper.title}</h2>
        <p><strong>Authors:</strong> ${paper.authors.join(', ')}</p>
        <p><strong>Published:</strong> ${paper.published}</p>
        <p>${paper.summary}</p>
        <a href="${paper.pdfLink}" target="_blank" class="btn">View PDF</a>
        <div class="citation-tools">
            <h3>Cite this paper</h3>
            <button id="bibtex-btn" class="btn">Copy BibTeX</button>
            <button id="citation-btn" class="btn">Copy Citation</button>
        </div>
        <p style="color: #666; font-style: italic; margin-top: 1rem;">
            Note: This is sample data. The actual paper details would be loaded from arXiv API if available.
        </p>
    `;
    
    setupCitationButtons(id, paper.title, paper.authors, paper.published);
}

function setupCitationButtons(id, title, authors, published) {
    const bibtexBtn = document.getElementById('bibtex-btn');
    const citationBtn = document.getElementById('citation-btn');
    
    bibtexBtn.addEventListener('click', () => {
        const bibtex = generateBibtex(id, title, authors, published);
        copyToClipboard(bibtex);
    });
    
    citationBtn.addEventListener('click', () => {
        const citation = generateStandardCitation(title, authors, published);
        copyToClipboard(citation);
    });
}

function generateBibtex(id, title, authors, published) {
    const year = new Date(published).getFullYear();
    const authorList = authors.map(name => {
        const parts = name.split(' ');
        return `${parts.pop()}, ${parts.join(' ')}`;
    }).join(' and ');
    
    return `@article{${id},
  title={${title}},
  author={${authorList}},
  journal={arXiv preprint arXiv:${id}},
  year={${year}}
}`;
}

function generateStandardCitation(title, authors, published) {
    const year = new Date(published).getFullYear();
    let authorText = authors.join(', ');
    
    if (authors.length > 1) {
        const lastAuthor = authors.pop();
        authorText = `${authors.join(', ')} and ${lastAuthor}`;
    }
    
    return `${authorText} (${year}). ${title}. arXiv preprint.`;
}

async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        alert('Copied to clipboard!');
    } catch (err) {
        console.error('Failed to copy: ', err);
        fallbackCopyTextToClipboard(text);
    }
}

function fallbackCopyTextToClipboard(text) {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    
    textArea.style.top = "0";
    textArea.style.left = "0";
    textArea.style.position = "fixed";
    
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    
    try {
        const successful = document.execCommand('copy');
        if (successful) {
            alert('Copied to clipboard!');
        } else {
            alert('Failed to copy');
        }
    } catch (err) {
        alert('Failed to copy');
    }
    
    document.body.removeChild(textArea);
}