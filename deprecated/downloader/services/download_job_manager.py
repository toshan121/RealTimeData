"""
Download Job Manager

Manages download jobs, scheduling, and queue processing.
Provides professional job management with persistence and recovery.

Following Single Responsibility: Only handles job management concerns.
"""

import json
import threading
import time
import queue
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum
import logging

from ..configuration.download_config import DownloadJobConfig, DownloadConfiguration
from ..exceptions import DownloadJobError
from .auto_downloader_service import AutoDownloaderService
from .progress_tracker import ProgressTracker, JobStatus


logger = logging.getLogger(__name__)


class JobPriority(Enum):
    """Job priority levels."""
    LOW = 1
    NORMAL = 2  
    HIGH = 3
    URGENT = 4


@dataclass
class DownloadJob:
    """Represents a download job with metadata."""
    job_id: str
    config: DownloadJobConfig
    priority: JobPriority = JobPriority.NORMAL
    created_time: datetime = None
    scheduled_time: Optional[datetime] = None
    started_time: Optional[datetime] = None
    completed_time: Optional[datetime] = None
    status: JobStatus = JobStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    error_message: str = ""
    result: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.created_time is None:
            self.created_time = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for serialization."""
        data = asdict(self)
        
        # Convert datetime objects to ISO strings
        for field in ['created_time', 'scheduled_time', 'started_time', 'completed_time']:
            if data[field]:
                data[field] = data[field].isoformat()
        
        # Convert enums to values
        data['priority'] = self.priority.value
        data['status'] = self.status.value
        
        # Convert config with special handling for complex types
        config_dict = asdict(self.config)
        
        # Convert DataType enums in data_types list
        if 'data_types' in config_dict and config_dict['data_types']:
            config_dict['data_types'] = [
                dt.value if hasattr(dt, 'value') else str(dt) 
                for dt in config_dict['data_types']
            ]
        
        data['config'] = config_dict
        
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DownloadJob':
        """Create job from dictionary."""
        # Convert datetime strings back to datetime objects
        for field in ['created_time', 'scheduled_time', 'started_time', 'completed_time']:
            if data.get(field):
                data[field] = datetime.fromisoformat(data[field])
        
        # Convert enum values back to enums
        if 'priority' in data:
            data['priority'] = JobPriority(data['priority'])
        if 'status' in data:
            data['status'] = JobStatus(data['status'])
        
        # Reconstruct config object
        if 'config' in data:
            config_data = data['config'].copy()
            
            # Convert data_types strings back to DataType enums
            if 'data_types' in config_data and config_data['data_types']:
                from ..configuration.download_config import DataType
                config_data['data_types'] = [
                    DataType(dt) if isinstance(dt, str) else dt
                    for dt in config_data['data_types']
                ]
            
            data['config'] = DownloadJobConfig(**config_data)
        
        return cls(**data)


class DownloadJobManager:
    """
    Professional download job manager with queue processing,
    scheduling, persistence, and recovery capabilities.
    """
    
    def __init__(self, config: DownloadConfiguration, 
                 downloader_service: AutoDownloaderService):
        """
        Initialize the job manager.
        
        Args:
            config: Download configuration
            downloader_service: The downloader service to use
        """
        self.config = config
        self.downloader_service = downloader_service
        self.progress_tracker = ProgressTracker()
        
        # Job storage
        self._jobs: Dict[str, DownloadJob] = {}
        self._job_queue = queue.PriorityQueue()
        self._completed_jobs: Dict[str, DownloadJob] = {}
        
        # Threading
        self._lock = threading.RLock()
        self._worker_threads: List[threading.Thread] = []
        self._running = False
        self._max_concurrent_jobs = config.data_source.concurrent_connections
        
        # Persistence
        self._persistence_file = config.storage.base_data_dir / "jobs" / "job_manager_state.json"
        self._persistence_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load persisted state
        self._load_state()
        
        logger.info(f"DownloadJobManager initialized with {self._max_concurrent_jobs} max concurrent jobs")
    
    def start(self):
        """Start the job manager and worker threads."""
        if self._running:
            logger.warning("Job manager already running")
            return
        
        logger.info("Starting DownloadJobManager")
        
        self._running = True
        
        # Start worker threads
        for i in range(self._max_concurrent_jobs):
            worker = threading.Thread(
                target=self._worker_thread,
                name=f"JobWorker-{i}",
                daemon=True
            )
            worker.start()
            self._worker_threads.append(worker)
        
        # Start persistence thread
        persistence_thread = threading.Thread(
            target=self._persistence_worker,
            name="JobPersistence",
            daemon=True
        )
        persistence_thread.start()
        self._worker_threads.append(persistence_thread)
        
        logger.info(f"Started {len(self._worker_threads)} worker threads")
    
    def stop(self):
        """Stop the job manager and worker threads."""
        if not self._running:
            return
        
        logger.info("Stopping DownloadJobManager")
        
        self._running = False
        
        # Save current state
        self._save_state()
        
        # Wait for workers to finish current jobs (with timeout)
        for worker in self._worker_threads:
            if worker.is_alive():
                worker.join(timeout=30)
        
        logger.info("DownloadJobManager stopped")
    
    def submit_job(self, job_config: DownloadJobConfig, 
                   priority: JobPriority = JobPriority.NORMAL,
                   scheduled_time: Optional[datetime] = None) -> str:
        """
        Submit a new download job.
        
        Args:
            job_config: Job configuration
            priority: Job priority
            scheduled_time: When to execute the job (None for immediate)
            
        Returns:
            Job ID
        """
        job = DownloadJob(
            job_id=job_config.job_id,
            config=job_config,
            priority=priority,
            scheduled_time=scheduled_time
        )
        
        with self._lock:
            self._jobs[job.job_id] = job
            
            # Add to queue with priority (lower number = higher priority)
            priority_value = -priority.value  # Negative for reverse order
            queue_item = (priority_value, time.time(), job.job_id)
            self._job_queue.put(queue_item)
        
        logger.info(f"Submitted job {job.job_id} with priority {priority.name}")
        
        return job.job_id
    
    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a pending or running job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            True if job was cancelled, False if not found or already completed
        """
        with self._lock:
            if job_id not in self._jobs:
                return False
            
            job = self._jobs[job_id]
            
            if job.status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                return False
            
            job.status = JobStatus.CANCELLED
            job.completed_time = datetime.now()
            
            # Move to completed jobs
            self._completed_jobs[job_id] = job
            del self._jobs[job_id]
        
        logger.info(f"Cancelled job {job_id}")
        return True
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific job."""
        with self._lock:
            if job_id in self._jobs:
                return self._jobs[job_id].to_dict()
            elif job_id in self._completed_jobs:
                return self._completed_jobs[job_id].to_dict()
            else:
                return None
    
    def list_jobs(self, status_filter: Optional[JobStatus] = None) -> List[Dict[str, Any]]:
        """
        List all jobs, optionally filtered by status.
        
        Args:
            status_filter: Only return jobs with this status
            
        Returns:
            List of job dictionaries
        """
        with self._lock:
            all_jobs = list(self._jobs.values()) + list(self._completed_jobs.values())
            
            if status_filter:
                all_jobs = [job for job in all_jobs if job.status == status_filter]
            
            # Sort by created time (newest first)
            all_jobs.sort(key=lambda x: x.created_time, reverse=True)
            
            return [job.to_dict() for job in all_jobs]
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get queue status and statistics."""
        with self._lock:
            pending_jobs = [job for job in self._jobs.values() if job.status == JobStatus.PENDING]
            running_jobs = [job for job in self._jobs.values() if job.status == JobStatus.RUNNING]
            
            return {
                'queue_size': len(pending_jobs),
                'running_jobs': len(running_jobs),
                'total_active_jobs': len(self._jobs),
                'completed_jobs': len(self._completed_jobs),
                'worker_threads': len(self._worker_threads),
                'max_concurrent_jobs': self._max_concurrent_jobs,
                'manager_running': self._running
            }
    
    def retry_failed_job(self, job_id: str) -> bool:
        """
        Retry a failed job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            True if job was requeued for retry, False otherwise
        """
        with self._lock:
            job = self._completed_jobs.get(job_id)
            if not job or job.status != JobStatus.FAILED:
                return False
            
            if job.retry_count >= job.max_retries:
                logger.warning(f"Job {job_id} has exceeded max retries ({job.max_retries})")
                return False
            
            # Reset job for retry
            job.status = JobStatus.PENDING
            job.started_time = None
            job.completed_time = None
            job.retry_count += 1
            job.error_message = ""
            
            # Move back to active jobs
            self._jobs[job_id] = job
            del self._completed_jobs[job_id]
            
            # Re-queue the job
            priority_value = -job.priority.value
            queue_item = (priority_value, time.time(), job.job_id)
            self._job_queue.put(queue_item)
        
        logger.info(f"Requeued job {job_id} for retry (attempt {job.retry_count})")
        return True
    
    def schedule_recurring_job(self, job_config: DownloadJobConfig,
                              interval: timedelta, start_time: Optional[datetime] = None) -> str:
        """
        Schedule a recurring job.
        
        Args:
            job_config: Base job configuration
            interval: Interval between job executions
            start_time: When to start the recurring schedule
            
        Returns:
            Recurring job ID
        """
        if start_time is None:
            start_time = datetime.now()
        
        # Create recurring job metadata
        recurring_job_id = f"recurring_{job_config.job_id}_{int(time.time())}"
        
        # For now, just schedule the first occurrence
        # A full implementation would handle the recurring logic
        first_job_config = DownloadJobConfig(
            job_id=f"{recurring_job_id}_001",
            symbols=job_config.symbols,
            start_date=job_config.start_date,
            end_date=job_config.end_date,
            data_types=job_config.data_types
        )
        
        self.submit_job(first_job_config, JobPriority.NORMAL, start_time)
        
        logger.info(f"Scheduled recurring job {recurring_job_id} starting at {start_time}")
        return recurring_job_id
    
    def _worker_thread(self):
        """Worker thread that processes jobs from the queue."""
        thread_name = threading.current_thread().name
        logger.info(f"Worker thread {thread_name} started")
        
        while self._running:
            try:
                # Get job from queue with timeout
                try:
                    priority_value, queue_time, job_id = self._job_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # Get job details
                with self._lock:
                    if job_id not in self._jobs:
                        continue  # Job was cancelled
                    
                    job = self._jobs[job_id]
                    
                    # Check if job is scheduled for future execution
                    if job.scheduled_time and job.scheduled_time > datetime.now():
                        # Re-queue for later
                        self._job_queue.put((priority_value, queue_time, job_id))
                        time.sleep(5)  # Wait before checking again
                        continue
                    
                    # Mark job as running
                    job.status = JobStatus.RUNNING
                    job.started_time = datetime.now()
                
                logger.info(f"Worker {thread_name} starting job {job_id}")
                
                # Execute the job
                try:
                    self._execute_job(job)
                    
                    with self._lock:
                        job.status = JobStatus.COMPLETED
                        job.completed_time = datetime.now()
                        
                except Exception as e:
                    logger.error(f"Job {job_id} failed: {e}")
                    
                    with self._lock:
                        job.status = JobStatus.FAILED
                        job.completed_time = datetime.now()
                        job.error_message = str(e)
                
                # Move completed job
                with self._lock:
                    self._completed_jobs[job_id] = job
                    del self._jobs[job_id]
                
                logger.info(f"Worker {thread_name} completed job {job_id} with status {job.status.value}")
                
            except Exception as e:
                logger.error(f"Worker thread {thread_name} error: {e}")
                time.sleep(1)  # Brief pause before continuing
        
        logger.info(f"Worker thread {thread_name} stopped")
    
    def _execute_job(self, job: DownloadJob):
        """Execute a download job."""
        logger.info(f"Executing job {job.job_id}")
        
        # Create a combined download for all symbols/dates/types
        results = []
        
        # Get date range
        dates = self._get_date_range(job.config.start_date, job.config.end_date)
        
        # Execute downloads
        for symbol in job.config.symbols:
            for date in dates:
                try:
                    # Download all data types for this symbol/date
                    result = self.downloader_service.download_single_symbol(
                        symbol, date, job.config.data_types
                    )
                    results.append(result)
                    
                except Exception as e:
                    logger.error(f"Failed to download {symbol} {date}: {e}")
                    results.append({
                        'symbol': symbol,
                        'date': date,
                        'status': 'failed',
                        'error': str(e)
                    })
                    
                    if not job.config.continue_on_error:
                        raise DownloadJobError(
                            f"Job {job.job_id} failed on {symbol} {date}: {e}",
                            job_id=job.job_id,
                            symbol=symbol,
                            date=date
                        )
        
        # Store job results
        job.result = {
            'total_downloads': len(results),
            'successful_downloads': len([r for r in results if r.get('overall_status') == 'success']),
            'failed_downloads': len([r for r in results if r.get('overall_status') != 'success']),
            'details': results
        }
        
        logger.info(f"Job {job.job_id} completed: {job.result['successful_downloads']}/{job.result['total_downloads']} successful")
    
    def _get_date_range(self, start_date: str, end_date: str) -> List[str]:
        """Get list of dates between start and end date."""
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        
        dates = []
        current = start
        while current <= end:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
            
        return dates
    
    def _persistence_worker(self):
        """Background thread for persisting job state."""
        logger.info("Persistence worker started")
        
        while self._running:
            try:
                time.sleep(60)  # Save state every minute
                self._save_state()
            except Exception as e:
                logger.error(f"Persistence worker error: {e}")
        
        logger.info("Persistence worker stopped")
    
    def _save_state(self):
        """Save job manager state to disk."""
        try:
            with self._lock:
                state = {
                    'jobs': {job_id: job.to_dict() for job_id, job in self._jobs.items()},
                    'completed_jobs': {job_id: job.to_dict() for job_id, job in self._completed_jobs.items()},
                    'saved_time': datetime.now().isoformat()
                }
            
            # Write to temporary file first, then rename (atomic operation)
            temp_file = self._persistence_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(state, f, indent=2)
            
            temp_file.rename(self._persistence_file)
            
        except Exception as e:
            logger.error(f"Failed to save job manager state: {e}")
    
    def _load_state(self):
        """Load job manager state from disk."""
        if not self._persistence_file.exists():
            logger.info("No persisted state found, starting fresh")
            return
        
        try:
            with open(self._persistence_file, 'r') as f:
                state = json.load(f)
            
            # Restore jobs
            for job_id, job_data in state.get('jobs', {}).items():
                try:
                    job = DownloadJob.from_dict(job_data)
                    
                    # Reset running jobs to pending on startup
                    if job.status == JobStatus.RUNNING:
                        job.status = JobStatus.PENDING
                        job.started_time = None
                    
                    self._jobs[job_id] = job
                    
                    # Re-queue pending jobs
                    if job.status == JobStatus.PENDING:
                        priority_value = -job.priority.value
                        queue_item = (priority_value, time.time(), job.job_id)
                        self._job_queue.put(queue_item)
                        
                except Exception as e:
                    logger.error(f"Failed to restore job {job_id}: {e}")
            
            # Restore completed jobs
            for job_id, job_data in state.get('completed_jobs', {}).items():
                try:
                    job = DownloadJob.from_dict(job_data)
                    self._completed_jobs[job_id] = job
                except Exception as e:
                    logger.error(f"Failed to restore completed job {job_id}: {e}")
            
            logger.info(f"Restored {len(self._jobs)} active jobs and {len(self._completed_jobs)} completed jobs")
            
        except Exception as e:
            logger.error(f"Failed to load job manager state: {e}")
    
    def cleanup_old_jobs(self, older_than_days: int = 7):
        """
        Clean up old completed jobs.
        
        Args:
            older_than_days: Remove completed jobs older than this many days
        """
        cutoff_time = datetime.now() - timedelta(days=older_than_days)
        
        with self._lock:
            jobs_to_remove = []
            
            for job_id, job in self._completed_jobs.items():
                if job.completed_time and job.completed_time < cutoff_time:
                    jobs_to_remove.append(job_id)
            
            for job_id in jobs_to_remove:
                del self._completed_jobs[job_id]
        
        logger.info(f"Cleaned up {len(jobs_to_remove)} old completed jobs")
        return len(jobs_to_remove)
    
    def pause_job_processing(self):
        """Pause job processing temporarily."""
        with self._lock:
            if self._running:
                self._running = False
                logger.info("Job processing paused")
                return True
            return False
    
    def resume_job_processing(self):
        """Resume job processing."""
        with self._lock:
            if not self._running:
                self._running = True
                # Restart workers if needed
                active_workers = [t for t in self._worker_threads if t.is_alive()]
                if len(active_workers) < self._max_concurrent_jobs:
                    self.start()  # This will restart the workers
                logger.info("Job processing resumed")
                return True
            return False
    
    def get_job_performance_metrics(self) -> Dict[str, Any]:
        """Get performance metrics for completed jobs."""
        with self._lock:
            completed_jobs = [job for job in self._completed_jobs.values() 
                            if job.status == JobStatus.COMPLETED and job.completed_time]
            
            if not completed_jobs:
                return {
                    'total_completed_jobs': 0,
                    'metrics_available': False
                }
            
            # Calculate durations
            durations = []
            for job in completed_jobs:
                if job.started_time and job.completed_time:
                    duration = (job.completed_time - job.started_time).total_seconds()
                    durations.append(duration)
            
            if not durations:
                return {
                    'total_completed_jobs': len(completed_jobs),
                    'metrics_available': False
                }
            
            # Calculate statistics
            avg_duration = sum(durations) / len(durations)
            min_duration = min(durations)
            max_duration = max(durations)
            
            # Calculate success rate
            total_jobs = len(self._completed_jobs)
            successful_jobs = len([job for job in self._completed_jobs.values() 
                                 if job.status == JobStatus.COMPLETED])
            success_rate = (successful_jobs / total_jobs * 100.0) if total_jobs > 0 else 0.0
            
            return {
                'total_completed_jobs': len(completed_jobs),
                'metrics_available': True,
                'average_duration_seconds': avg_duration,
                'min_duration_seconds': min_duration,
                'max_duration_seconds': max_duration,
                'success_rate_percent': success_rate,
                'total_jobs_processed': total_jobs,
                'last_calculated': datetime.now().isoformat()
            }
    
    def export_job_history(self, file_path: str, status_filter: Optional[JobStatus] = None,
                          include_results: bool = False) -> Dict[str, Any]:
        """
        Export job history to JSON file with enhanced options.
        
        Args:
            file_path: Path to save the export
            status_filter: Only export jobs with this status
            include_results: Whether to include detailed job results
            
        Returns:
            Export summary
        """
        with self._lock:
            # Get jobs to export
            jobs_to_export = []
            
            for job_collection in [self._jobs, self._completed_jobs]:
                for job in job_collection.values():
                    if status_filter is None or job.status == status_filter:
                        job_dict = job.to_dict()
                        
                        # Optionally remove large result data
                        if not include_results and 'result' in job_dict:
                            job_dict['result'] = {
                                'summary_only': True,
                                'original_result_size': len(str(job_dict['result']))
                            }
                        
                        jobs_to_export.append(job_dict)
            
            # Sort by created time
            jobs_to_export.sort(key=lambda x: x['created_time'], reverse=True)
            
            export_data = {
                'export_metadata': {
                    'export_time': datetime.now().isoformat(),
                    'total_jobs_exported': len(jobs_to_export),
                    'status_filter': status_filter.value if status_filter else None,
                    'include_results': include_results,
                    'exporter_version': '1.0'
                },
                'queue_status_at_export': self.get_queue_status(),
                'performance_metrics': self.get_job_performance_metrics(),
                'jobs': jobs_to_export
            }
            
            # Write to file
            try:
                with open(file_path, 'w') as f:
                    json.dump(export_data, f, indent=2)
                
                export_summary = {
                    'export_successful': True,
                    'file_path': file_path,
                    'jobs_exported': len(jobs_to_export),
                    'file_size_bytes': Path(file_path).stat().st_size
                }
                
                logger.info(f"Exported {len(jobs_to_export)} jobs to {file_path}")
                return export_summary
                
            except Exception as e:
                logger.error(f"Failed to export job history: {e}")
                return {
                    'export_successful': False,
                    'error': str(e),
                    'jobs_attempted': len(jobs_to_export)
                }
    
    def validate_job_integrity(self) -> Dict[str, Any]:
        """
        Validate integrity of job data and identify any inconsistencies.
        
        Returns:
            Validation results
        """
        with self._lock:
            validation_results = {
                'validation_time': datetime.now().isoformat(),
                'total_jobs_checked': 0,
                'issues_found': [],
                'integrity_score': 100.0
            }
            
            all_jobs = list(self._jobs.values()) + list(self._completed_jobs.values())
            validation_results['total_jobs_checked'] = len(all_jobs)
            
            for job in all_jobs:
                # Check for missing required fields
                if not job.job_id:
                    validation_results['issues_found'].append({
                        'type': 'missing_job_id',
                        'job_reference': str(job),
                        'severity': 'high'
                    })
                
                # Check timestamp consistency
                if job.started_time and job.created_time:
                    if job.started_time < job.created_time:
                        validation_results['issues_found'].append({
                            'type': 'invalid_timestamp_order',
                            'job_id': job.job_id,
                            'details': 'Start time before create time',
                            'severity': 'medium'
                        })
                
                if job.completed_time and job.started_time:
                    if job.completed_time < job.started_time:
                        validation_results['issues_found'].append({
                            'type': 'invalid_timestamp_order',
                            'job_id': job.job_id,
                            'details': 'Complete time before start time',
                            'severity': 'medium'
                        })
                
                # Check status consistency
                if job.status == JobStatus.COMPLETED and not job.completed_time:
                    validation_results['issues_found'].append({
                        'type': 'status_timestamp_mismatch',
                        'job_id': job.job_id,
                        'details': 'Job marked completed but no completion time',
                        'severity': 'medium'
                    })
                
                if job.status == JobStatus.FAILED and not job.error_message:
                    validation_results['issues_found'].append({
                        'type': 'missing_error_message',
                        'job_id': job.job_id,
                        'details': 'Job marked failed but no error message',
                        'severity': 'low'
                    })
                
                # Check retry count consistency
                if job.retry_count > job.max_retries:
                    validation_results['issues_found'].append({
                        'type': 'retry_count_exceeded',
                        'job_id': job.job_id,
                        'details': f'Retry count ({job.retry_count}) exceeds max ({job.max_retries})',
                        'severity': 'low'
                    })
            
            # Calculate integrity score
            total_issues = len(validation_results['issues_found'])
            high_severity_issues = len([i for i in validation_results['issues_found'] if i['severity'] == 'high'])
            medium_severity_issues = len([i for i in validation_results['issues_found'] if i['severity'] == 'medium'])
            
            if total_issues > 0:
                # Deduct points based on severity
                score_deduction = (high_severity_issues * 20) + (medium_severity_issues * 10) + (total_issues - high_severity_issues - medium_severity_issues) * 2
                validation_results['integrity_score'] = max(0.0, 100.0 - score_deduction)
            
            validation_results['summary'] = {
                'high_severity_issues': high_severity_issues,
                'medium_severity_issues': medium_severity_issues,
                'low_severity_issues': total_issues - high_severity_issues - medium_severity_issues,
                'overall_health': 'good' if validation_results['integrity_score'] >= 90 else 'fair' if validation_results['integrity_score'] >= 70 else 'poor'
            }
            
            return validation_results