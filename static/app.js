document.addEventListener('DOMContentLoaded', function() {
    // Initialize form and file upload components
    const form = document.getElementById('uploadForm');
    const progressSection = document.getElementById('progressSection');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    
    // File upload components
    const fileUploads = [
        {
            input: document.getElementById('assignmentFile'),
            dropzone: document.getElementById('assignmentDropzone'),
            preview: document.getElementById('assignmentPreview'),
            isMultiple: false,
            isRequired: true
        },
        {
            input: document.getElementById('submissionsFile'),
            dropzone: document.getElementById('submissionsDropzone'),
            preview: document.getElementById('submissionsPreview'),
            isMultiple: true,
            isRequired: true
        },
        {
            input: document.getElementById('solutionFile'),
            dropzone: document.getElementById('solutionDropzone'),
            preview: document.getElementById('solutionPreview'),
            isMultiple: false,
            isRequired: false
        },
        {
            input: document.getElementById('rubricFile'),
            dropzone: document.getElementById('rubricDropzone'),
            preview: document.getElementById('rubricPreview'),
            isMultiple: false,
            isRequired: false
        }
    ];
    
    // Maximum file size in bytes (10MB)
    const MAX_FILE_SIZE = 10 * 1024 * 1024;
    
    // Initialize file upload components
    fileUploads.forEach(fileUpload => {
        initializeFileUpload(fileUpload);
    });
    
    // Form submission
    form.addEventListener('submit', function(e) {
        e.preventDefault();
        
        // Validate form
        if (validateForm()) {
            // Show progress
            startUploadProcess();
        }
    });
    
    // Initialize file upload component
    function initializeFileUpload(fileUpload) {
        const { input, dropzone, preview, isMultiple } = fileUpload;
        
        // Browse files button click
        const browseButton = dropzone.querySelector('.file-upload__button');
        if (browseButton) {
            browseButton.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                input.click();
            });
        }
        
        // Click on dropzone
        dropzone.addEventListener('click', function() {
            input.click();
        });
        
        // File selection
        input.addEventListener('change', function() {
            handleFiles(this.files, fileUpload);
        });
        
        // Drag and drop
        dropzone.addEventListener('dragover', function(e) {
            e.preventDefault();
            this.classList.add('drag-over');
        });
        
        dropzone.addEventListener('dragleave', function() {
            this.classList.remove('drag-over');
        });
        
        dropzone.addEventListener('drop', function(e) {
            e.preventDefault();
            this.classList.remove('drag-over');
            
            if (e.dataTransfer.files.length > 0) {
                handleFiles(e.dataTransfer.files, fileUpload);
            }
        });
    }
    
    // Handle selected files
    function handleFiles(files, fileUpload) {
        const { input, preview, isMultiple, isRequired } = fileUpload;
        const parent = input.parentElement;
        
        // Remove any existing error
        clearError(parent);
        
        // Validate files
        const validFiles = [];
        let errorMessage = '';
        
        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            
            // Check file type (must be PDF)
            if (!file.type.match('application/pdf')) {
                errorMessage = 'Only PDF files are allowed';
                break;
            }
            
            // Check file size
            if (file.size > MAX_FILE_SIZE) {
                errorMessage = 'File size must not exceed 10MB';
                break;
            }
            
            validFiles.push(file);
            
            // For single file upload, only take the first file
            if (!isMultiple && validFiles.length > 0) {
                break;
            }
        }
        
        // Show error if any
        if (errorMessage) {
            showError(parent, errorMessage);
            return;
        }
        
        // Clear preview for single file upload
        if (!isMultiple) {
            preview.innerHTML = '';
        }
        
        // Display selected files
        validFiles.forEach(file => {
            displayFile(file, preview, fileUpload);
        });
        
        // Show the preview if files are selected
        if (validFiles.length > 0 && preview.children.length > 0) {
            preview.style.display = 'block';
        } else if (preview.children.length === 0) {
            preview.style.display = 'none';
        }
    }
    
    // Display a file in the preview
    function displayFile(file, preview, fileUpload) {
        const fileItem = document.createElement('div');
        fileItem.className = 'file-item';
        
        const fileSize = formatFileSize(file.size);
        
        fileItem.innerHTML = `
            <div class="file-item__info">
                <div class="file-item__icon">📄</div>
                <div>
                    <div class="file-item__name">${file.name}</div>
                    <div class="file-item__size">${fileSize}</div>
                </div>
            </div>
            <button type="button" class="file-item__remove" title="Remove file">×</button>
        `;
        
        // Remove file button
        const removeButton = fileItem.querySelector('.file-item__remove');
        removeButton.addEventListener('click', function() {
            fileItem.remove();
            
            // If no files left in preview, hide it
            if (preview.children.length === 0) {
                preview.style.display = 'none';
            }
            
            // If the upload is required, check if we need to show validation error
            if (fileUpload.isRequired) {
                validateFileUpload(fileUpload);
            }
        });
        
        preview.appendChild(fileItem);
    }
    
    // Format file size
    function formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }
    
    // Validate form
    function validateForm() {
        let isValid = true;
        
        // Validate select elements
        const subject = document.getElementById('subject');
        const assignmentType = document.getElementById('assignmentType');
        
        if (!subject.value) {
            showError(subject.parentElement, 'Please select a subject');
            isValid = false;
        } else {
            clearError(subject.parentElement);
        }
        
        if (!assignmentType.value) {
            showError(assignmentType.parentElement, 'Please select an assignment type');
            isValid = false;
        } else {
            clearError(assignmentType.parentElement);
        }
        
        // Validate file uploads
        fileUploads.forEach(fileUpload => {
            if (fileUpload.isRequired) {
                if (!validateFileUpload(fileUpload)) {
                    isValid = false;
                }
            }
        });
        
        return isValid;
    }
    
    // Validate a file upload
    function validateFileUpload(fileUpload) {
        const { preview, input } = fileUpload;
        const parent = input.parentElement;
        
        if (preview.children.length === 0) {
            showError(parent, 'This file is required');
            return false;
        } else {
            clearError(parent);
            return true;
        }
    }
    
    // Show error message
    function showError(element, message) {
        // Add error class
        element.classList.add('is-invalid');
        
        // Remove existing error message
        const existingError = element.querySelector('.invalid-feedback');
        if (existingError) {
            existingError.remove();
        }
        
        // Create and append error message
        const errorElement = document.createElement('div');
        errorElement.className = 'invalid-feedback';
        errorElement.textContent = message;
        element.appendChild(errorElement);
    }
    
    // Clear error message
    function clearError(element) {
        // Remove error class
        element.classList.remove('is-invalid');
        
        // Remove error message
        const existingError = element.querySelector('.invalid-feedback');
        if (existingError) {
            existingError.remove();
        }
    }
    
    // Start upload process with progress bar
    function startUploadProcess() {
        // Hide form and show progress
        form.classList.add('hidden');
        progressSection.classList.remove('hidden');
        
        // Initialize progress
        progressFill.style.width = '0%';
        progressText.textContent = 'Uploading files...';
        
        // Simulate progress
        let progress = 0;
        const interval = setInterval(() => {
            progress += Math.random() * 10;
            
            if (progress >= 100) {
                progress = 100;
                clearInterval(interval);
                
                // Update text
                progressText.textContent = 'Upload complete! Redirecting to dashboard...';
                
                // Simulate redirect after a delay
                setTimeout(() => {
                    // For demo purposes, reset the form
                    resetDemo();
                }, 1500);
            }
            
            // Update progress bar
            progressFill.style.width = `${progress}%`;
            
            // Update text at different stages
            if (progress > 30 && progress < 60) {
                progressText.textContent = 'Processing files...';
            } else if (progress >= 60 && progress < 90) {
                progressText.textContent = 'Preparing AI grading...';
            } else if (progress >= 90 && progress < 100) {
                progressText.textContent = 'Almost done...';
            }
        }, 200);
    }
    
    // Reset demo (for demonstration purposes only)
    function resetDemo() {
        // For the purpose of the demo, reset the form after the "redirect"
        setTimeout(() => {
            form.reset();
            form.classList.remove('hidden');
            progressSection.classList.add('hidden');
            
            // Clear all file displays
            fileUploads.forEach(fileUpload => {
                const { preview } = fileUpload;
                preview.innerHTML = '';
                preview.style.display = 'none';
            });
        }, 500);
    }
});