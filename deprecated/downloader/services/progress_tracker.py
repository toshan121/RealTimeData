"""
Progress Tracker Service

Real-time progress tracking and status monitoring for download jobs.
Provides thread-safe progress updates and status queries.

Following Single Responsibility: Only handles progress tracking concerns.
"""

import threading
import time
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

from ..exceptions import ProgressTrackingError


class JobStatus(Enum):
    """Possible job statuses."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobProgress:
    """Progress information for a download job."""
    job_id: str
    status: JobStatus
    start_time: datetime
    end_time: Optional[datetime] = None
    current_step: int = 0
    total_steps: int = 0
    current_message: str = ""
    error_message: str = ""
    completion_percentage: float = 0.0
    
    # Performance metrics
    steps_per_second: float = 0.0
    estimated_completion: Optional[datetime] = None
    
    # Metadata
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def update_progress(self, step: int, message: str = ""):
        """Update progress information."""
        self.current_step = step
        self.current_message = message
        
        if self.total_steps > 0:
            self.completion_percentage = (step / self.total_steps) * 100.0
        
        # Calculate performance metrics
        if self.status == JobStatus.RUNNING:
            elapsed_time = (datetime.now() - self.start_time).total_seconds()
            if elapsed_time > 0 and step > 0:
                self.steps_per_second = step / elapsed_time
                
                if self.steps_per_second > 0:
                    remaining_steps = self.total_steps - step
                    remaining_seconds = remaining_steps / self.steps_per_second
                    self.estimated_completion = datetime.now() + timedelta(seconds=remaining_seconds)
    
    def complete(self, message: str = ""):
        """Mark job as completed."""
        self.status = JobStatus.COMPLETED
        self.end_time = datetime.now()
        self.current_step = self.total_steps
        self.completion_percentage = 100.0
        if message:
            self.current_message = message
    
    def fail(self, error_message: str):
        """Mark job as failed."""
        self.status = JobStatus.FAILED
        self.end_time = datetime.now()
        self.error_message = error_message
    
    def cancel(self):
        """Mark job as cancelled."""
        self.status = JobStatus.CANCELLED
        self.end_time = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        
        # Convert datetime objects to ISO strings
        data['start_time'] = self.start_time.isoformat()
        if self.end_time:
            data['end_time'] = self.end_time.isoformat()
        if self.estimated_completion:
            data['estimated_completion'] = self.estimated_completion.isoformat()
        
        # Convert enum to string
        data['status'] = self.status.value
        
        return data


class ProgressTracker:
    """
    Thread-safe progress tracker for download jobs.
    
    Provides real-time progress monitoring, status queries, and performance metrics
    for concurrent download operations.
    """
    
    def __init__(self):
        """Initialize the progress tracker."""
        self._jobs: Dict[str, JobProgress] = {}
        self._lock = threading.RLock()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._cleanup_interval = 3600  # 1 hour
        self._max_completed_jobs = 1000  # Keep last 1000 completed jobs
        
        # Start cleanup thread
        self._start_cleanup_thread()
    
    def start_job(self, job_id: str, total_steps: int = 0, 
                  metadata: Optional[Dict[str, Any]] = None) -> JobProgress:
        """
        Start tracking a new job.
        
        Args:
            job_id: Unique identifier for the job
            total_steps: Total number of steps expected (0 if unknown)
            metadata: Additional metadata for the job
            
        Returns:
            JobProgress object for the new job
            
        Raises:
            ProgressTrackingError: If job already exists
        """
        with self._lock:
            if job_id in self._jobs:
                raise ProgressTrackingError(
                    f"Job already exists: {job_id}",
                    tracker_id=job_id,
                    operation="start_job"
                )
            
            job_progress = JobProgress(
                job_id=job_id,
                status=JobStatus.RUNNING,
                start_time=datetime.now(),
                total_steps=total_steps,
                metadata=metadata or {}
            )
            
            self._jobs[job_id] = job_progress
            
            return job_progress
    
    def update_progress(self, job_id: str, step: Optional[int] = None,
                       message: str = "", metadata_update: Optional[Dict[str, Any]] = None):
        """
        Update progress for a job.
        
        Args:
            job_id: Job identifier
            step: Current step number (if None, increment by 1)
            message: Progress message
            metadata_update: Additional metadata to merge
            
        Raises:
            ProgressTrackingError: If job not found
        """
        with self._lock:
            if job_id not in self._jobs:
                raise ProgressTrackingError(
                    f"Job not found: {job_id}",
                    tracker_id=job_id,
                    operation="update_progress"
                )
            
            job = self._jobs[job_id]
            
            # Update step
            if step is not None:
                job.update_progress(step, message)
            else:
                job.update_progress(job.current_step + 1, message)
            
            # Update metadata
            if metadata_update:
                job.metadata.update(metadata_update)
    
    def complete_job(self, job_id: str, final_message: str = ""):
        """
        Mark a job as completed.
        
        Args:
            job_id: Job identifier
            final_message: Final completion message
            
        Raises:
            ProgressTrackingError: If job not found
        """
        with self._lock:
            if job_id not in self._jobs:
                raise ProgressTrackingError(
                    f"Job not found: {job_id}",
                    tracker_id=job_id,
                    operation="complete_job"
                )
            
            self._jobs[job_id].complete(final_message)
    
    def fail_job(self, job_id: str, error_message: str):
        """
        Mark a job as failed.
        
        Args:
            job_id: Job identifier
            error_message: Error description
            
        Raises:
            ProgressTrackingError: If job not found
        """
        with self._lock:
            if job_id not in self._jobs:
                raise ProgressTrackingError(
                    f"Job not found: {job_id}",
                    tracker_id=job_id,
                    operation="fail_job"
                )
            
            self._jobs[job_id].fail(error_message)
    
    def cancel_job(self, job_id: str):
        """
        Cancel a job.
        
        Args:
            job_id: Job identifier
            
        Raises:
            ProgressTrackingError: If job not found
        """
        with self._lock:
            if job_id not in self._jobs:
                raise ProgressTrackingError(
                    f"Job not found: {job_id}",
                    tracker_id=job_id,
                    operation="cancel_job"
                )
            
            self._jobs[job_id].cancel()
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status of a specific job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Job status dictionary or None if not found
        """
        with self._lock:
            if job_id not in self._jobs:
                return None
            
            return self._jobs[job_id].to_dict()
    
    def get_all_jobs(self, status_filter: Optional[JobStatus] = None) -> List[Dict[str, Any]]:
        """
        Get status of all jobs, optionally filtered by status.
        
        Args:
            status_filter: Only return jobs with this status
            
        Returns:
            List of job status dictionaries
        """
        with self._lock:
            jobs = []
            for job in self._jobs.values():
                if status_filter is None or job.status == status_filter:
                    jobs.append(job.to_dict())
            
            # Sort by start time (newest first)
            jobs.sort(key=lambda x: x['start_time'], reverse=True)
            
            return jobs
    
    def get_active_jobs(self) -> List[Dict[str, Any]]:
        """Get all active (running) jobs."""
        return self.get_all_jobs(JobStatus.RUNNING)
    
    def get_completed_jobs(self) -> List[Dict[str, Any]]:
        """Get all completed jobs."""
        return self.get_all_jobs(JobStatus.COMPLETED)
    
    def get_failed_jobs(self) -> List[Dict[str, Any]]:
        """Get all failed jobs."""
        return self.get_all_jobs(JobStatus.FAILED)
    
    def get_job_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics for all jobs.
        
        Returns:
            Summary statistics dictionary
        """
        with self._lock:
            total_jobs = len(self._jobs)
            
            status_counts = {status.value: 0 for status in JobStatus}
            for job in self._jobs.values():
                status_counts[job.status.value] += 1
            
            # Calculate performance metrics for completed jobs
            completed_jobs = [job for job in self._jobs.values() if job.status == JobStatus.COMPLETED]
            
            avg_duration = 0.0
            if completed_jobs:
                total_duration = sum(
                    (job.end_time - job.start_time).total_seconds() 
                    for job in completed_jobs
                )
                avg_duration = total_duration / len(completed_jobs)
            
            return {
                'total_jobs': total_jobs,
                'status_counts': status_counts,
                'active_jobs': status_counts[JobStatus.RUNNING.value],
                'completed_jobs': status_counts[JobStatus.COMPLETED.value],
                'failed_jobs': status_counts[JobStatus.FAILED.value],
                'success_rate': (
                    status_counts[JobStatus.COMPLETED.value] / total_jobs * 100.0
                    if total_jobs > 0 else 0.0
                ),
                'average_duration_seconds': avg_duration,
                'last_update': datetime.now().isoformat()
            }
    
    def clear_completed_jobs(self):
        """Clear all completed and failed jobs from memory."""
        with self._lock:
            active_jobs = {
                job_id: job for job_id, job in self._jobs.items()
                if job.status in [JobStatus.RUNNING, JobStatus.PENDING]
            }
            
            cleared_count = len(self._jobs) - len(active_jobs)
            self._jobs = active_jobs
            
            return cleared_count
    
    def export_job_history(self, file_path: str, status_filter: Optional[JobStatus] = None):
        """
        Export job history to JSON file.
        
        Args:
            file_path: Path to save the export
            status_filter: Only export jobs with this status
        """
        jobs = self.get_all_jobs(status_filter)
        
        export_data = {
            'export_time': datetime.now().isoformat(),
            'total_jobs': len(jobs),
            'status_filter': status_filter.value if status_filter else None,
            'jobs': jobs
        }
        
        with open(file_path, 'w') as f:
            json.dump(export_data, f, indent=2)
    
    def _start_cleanup_thread(self):
        """Start background thread for periodic cleanup."""
        def cleanup_worker():
            while True:
                try:
                    time.sleep(self._cleanup_interval)
                    self._cleanup_old_jobs()
                except Exception as e:
                    # Log error but continue running
                    pass
        
        self._cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        self._cleanup_thread.start()
    
    def _cleanup_old_jobs(self):
        """Remove old completed jobs to prevent memory growth."""
        with self._lock:
            # Get completed and failed jobs sorted by end time
            finished_jobs = [
                (job_id, job) for job_id, job in self._jobs.items()
                if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]
                and job.end_time is not None
            ]
            
            # Sort by end time (oldest first)
            finished_jobs.sort(key=lambda x: x[1].end_time)
            
            # Keep only the most recent ones
            if len(finished_jobs) > self._max_completed_jobs:
                jobs_to_remove = finished_jobs[:-self._max_completed_jobs]
                
                for job_id, _ in jobs_to_remove:
                    del self._jobs[job_id]
    
    def shutdown(self):
        """Shutdown the progress tracker and cleanup resources."""
        # The cleanup thread is daemon, so it will stop when main program exits
        pass