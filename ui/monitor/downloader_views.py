"""
Django Views for Downloader Management Interface

Professional web interface for managing historical data downloads.
Provides dashboard, job management, and configuration views.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.utils import timezone
from datetime import datetime, timedelta
import json
import logging

from .models import (
    DownloadJob, 
    DownloadConfiguration, 
    DownloadProgress,
    SystemConfiguration,
    DownloadAlert
)
from .services import get_downloader_service, ConfigurationService
from .forms import JobSubmissionForm, ConfigurationForm


logger = logging.getLogger(__name__)


@login_required
def downloader_dashboard(request):
    """
    Main downloader dashboard view.
    
    Shows system overview, active jobs, recent activity, and key metrics.
    """
    try:
        # Get recent statistics
        stats = {
            'total_jobs': DownloadJob.objects.count(),
            'active_jobs': DownloadJob.objects.filter(status__in=['pending', 'running']).count(),
            'completed_jobs': DownloadJob.objects.filter(status='completed').count(),
            'failed_jobs': DownloadJob.objects.filter(status='failed').count(),
        }
        
        # Get recent jobs (last 10)
        recent_jobs = DownloadJob.objects.order_by('-created_at')[:10]
        
        # Get active jobs with progress
        active_jobs = DownloadJob.objects.filter(
            status__in=['pending', 'running']
        ).order_by('-created_at')[:5]
        
        # Get recent alerts
        recent_alerts = DownloadAlert.objects.filter(
            is_read=False
        ).order_by('-created_at')[:5]
        
        # Get system status
        downloader_service = get_downloader_service()
        system_status = downloader_service.get_system_status()
        
        # Get active configurations
        active_configs = DownloadConfiguration.objects.filter(is_active=True).count()
        
        context = {
            'stats': stats,
            'recent_jobs': recent_jobs,
            'active_jobs': active_jobs,
            'recent_alerts': recent_alerts,
            'system_status': system_status,
            'active_configs': active_configs,
            'page_title': 'Downloader Dashboard'
        }
        
        return render(request, 'monitor/downloader_dashboard.html', context)
        
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        messages.error(request, f"Dashboard error: {str(e)}")
        return render(request, 'monitor/error.html', {'error': str(e)})


@login_required 
def job_list_view(request):
    """
    Job list view with filtering and pagination.
    """
    try:
        # Get all jobs
        jobs = DownloadJob.objects.all().order_by('-created_at')
        
        # Apply filters
        status_filter = request.GET.get('status')
        if status_filter:
            jobs = jobs.filter(status=status_filter)
        
        symbol_filter = request.GET.get('symbol')
        if symbol_filter:
            jobs = jobs.filter(symbols__contains=[symbol_filter.upper()])
        
        config_filter = request.GET.get('configuration')
        if config_filter:
            jobs = jobs.filter(configuration_id=config_filter)
        
        search_query = request.GET.get('search')
        if search_query:
            jobs = jobs.filter(
                Q(job_id__icontains=search_query) |
                Q(name__icontains=search_query) |
                Q(description__icontains=search_query)
            )
        
        # Pagination
        paginator = Paginator(jobs, 20)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)
        
        # Get configurations for filter dropdown
        configurations = DownloadConfiguration.objects.filter(is_active=True)
        
        # Get status choices for filter dropdown
        status_choices = DownloadJob.STATUS_CHOICES
        
        context = {
            'page_obj': page_obj,
            'jobs': page_obj,
            'configurations': configurations,
            'status_choices': status_choices,
            'current_filters': {
                'status': status_filter,
                'symbol': symbol_filter,
                'configuration': config_filter,
                'search': search_query
            },
            'page_title': 'Download Jobs'
        }
        
        return render(request, 'monitor/job_list.html', context)
        
    except Exception as e:
        logger.error(f"Job list error: {e}")
        messages.error(request, f"Error loading jobs: {str(e)}")
        return render(request, 'monitor/error.html', {'error': str(e)})


@login_required
def job_detail_view(request, job_id):
    """
    Detailed view of a specific job.
    """
    try:
        job = get_object_or_404(DownloadJob, job_id=job_id)
        
        # Get progress entries
        progress_entries = DownloadProgress.objects.filter(
            job=job
        ).order_by('created_at')
        
        # Get live progress from downloader service
        downloader_service = get_downloader_service()
        live_progress = downloader_service.get_job_progress(job_id)
        
        # Handle job actions
        if request.method == 'POST':
            action = request.POST.get('action')
            
            if action == 'cancel' and job.status in ['pending', 'running']:
                success = downloader_service.cancel_job(job_id)
                if success:
                    job.mark_cancelled()
                    messages.success(request, f'Job {job_id} cancelled successfully')
                else:
                    messages.warning(request, f'Job {job_id} cancellation requested')
                
            elif action == 'retry' and job.status == 'failed':
                success = downloader_service.retry_job(job_id)
                if success:
                    messages.success(request, f'Job {job_id} requeued for retry')
                else:
                    messages.error(request, f'Job {job_id} retry failed - max retries exceeded')
            
            elif action == 'delete' and job.status in ['completed', 'failed', 'cancelled']:
                job_id_copy = job.job_id
                job.delete()
                messages.success(request, f'Job {job_id_copy} deleted successfully')
                return redirect('monitor:job_list')
                
            else:
                messages.error(request, f'Invalid action "{action}" for job status "{job.status}"')
            
            return redirect('monitor:job_detail', job_id=job_id)
        
        context = {
            'job': job,
            'progress_entries': progress_entries,
            'live_progress': live_progress,
            'page_title': f'Job: {job_id}'
        }
        
        return render(request, 'monitor/job_detail.html', context)
        
    except Exception as e:
        logger.error(f"Job detail error: {e}")
        messages.error(request, f"Error loading job details: {str(e)}")
        return render(request, 'monitor/error.html', {'error': str(e)})


@login_required
def job_submit_view(request):
    """
    Job submission form view.
    """
    if request.method == 'POST':
        try:
            # Get form data
            configuration_id = request.POST.get('configuration')
            symbols_text = request.POST.get('symbols', '')
            start_date = request.POST.get('start_date')
            end_date = request.POST.get('end_date')
            data_types = request.POST.getlist('data_types')
            
            # Parse symbols
            symbols = [s.strip().upper() for s in symbols_text.split('\n') if s.strip()]
            
            if not symbols:
                messages.error(request, 'At least one symbol is required')
                return render(request, 'monitor/job_submit.html', {
                    'configurations': DownloadConfiguration.objects.filter(is_active=True),
                    'data_types': ['tick', 'level1', 'level2']
                })
            
            # Get configuration
            configuration = get_object_or_404(DownloadConfiguration, id=configuration_id)
            
            # Generate job ID
            job_id = f"job_{int(timezone.now().timestamp())}"
            
            # Create job
            job = DownloadJob.objects.create(
                job_id=job_id,
                name=request.POST.get('name', f'Download {len(symbols)} symbols'),
                description=request.POST.get('description', ''),
                configuration=configuration,
                symbols=symbols,
                start_date=datetime.strptime(start_date, '%Y-%m-%d').date(),
                end_date=datetime.strptime(end_date, '%Y-%m-%d').date(),
                data_types=data_types,
                priority=int(request.POST.get('priority', 2)),
                max_concurrent_symbols=int(request.POST.get('max_concurrent_symbols', 2)),
                max_retries=int(request.POST.get('max_retries', 3)),
                continue_on_error=request.POST.get('continue_on_error') == 'on',
                skip_existing=request.POST.get('skip_existing') == 'on',
                force_redownload=request.POST.get('force_redownload') == 'on',
                created_by=request.user
            )
            
            # Submit to downloader service
            downloader_service = get_downloader_service()
            downloader_service.submit_job(job)
            
            messages.success(request, f'Job {job_id} submitted successfully')
            return redirect('monitor:job_detail', job_id=job_id)
            
        except Exception as e:
            logger.error(f"Job submission error: {e}")
            messages.error(request, f"Job submission failed: {str(e)}")
    
    # GET request - show form
    configurations = DownloadConfiguration.objects.filter(is_active=True)
    data_types = ['tick', 'level1', 'level2']
    
    context = {
        'configurations': configurations,
        'data_types': data_types,
        'page_title': 'Submit New Job'
    }
    
    return render(request, 'monitor/job_submit.html', context)


@login_required
def configuration_list_view(request):
    """
    Configuration list and management view.
    """
    try:
        configurations = DownloadConfiguration.objects.all().order_by('-is_default', '-created_at')
        
        # Handle configuration actions
        if request.method == 'POST':
            action = request.POST.get('action')
            config_id = request.POST.get('config_id')
            
            if action == 'set_default' and config_id:
                success = ConfigurationService.set_default_configuration(int(config_id))
                if success:
                    messages.success(request, 'Default configuration updated')
                else:
                    messages.error(request, 'Failed to update default configuration')
                    
            elif action == 'validate' and config_id:
                config = get_object_or_404(DownloadConfiguration, id=config_id)
                validation_result = ConfigurationService.validate_configuration(config)
                
                if validation_result['is_valid']:
                    messages.success(request, f'Configuration "{config.name}" is valid')
                else:
                    messages.error(request, f'Configuration "{config.name}" validation failed')
            
            return redirect('monitor:configuration_list')
        
        context = {
            'configurations': configurations,
            'page_title': 'Download Configurations'
        }
        
        return render(request, 'monitor/configuration_list.html', context)
        
    except Exception as e:
        logger.error(f"Configuration list error: {e}")
        messages.error(request, f"Error loading configurations: {str(e)}")
        return render(request, 'monitor/error.html', {'error': str(e)})


@login_required
@require_http_methods(["POST"])
def job_action_ajax(request):
    """
    AJAX endpoint for job actions (cancel, retry, delete).
    """
    try:
        data = json.loads(request.body)
        job_id = data.get('job_id')
        action = data.get('action')
        
        if not job_id or not action:
            return JsonResponse({'success': False, 'error': 'Missing job_id or action'})
        
        job = get_object_or_404(DownloadJob, job_id=job_id)
        downloader_service = get_downloader_service()
        
        if action == 'cancel':
            if job.status in ['pending', 'running']:
                success = downloader_service.cancel_job(job_id)
                if success:
                    job.mark_cancelled()
                    return JsonResponse({'success': True, 'message': 'Job cancelled'})
                else:
                    return JsonResponse({'success': False, 'error': 'Cancellation failed'})
            else:
                return JsonResponse({'success': False, 'error': f'Cannot cancel job in {job.status} status'})
        
        elif action == 'retry':
            if job.status == 'failed':
                success = downloader_service.retry_job(job_id)
                if success:
                    return JsonResponse({'success': True, 'message': 'Job queued for retry'})
                else:
                    return JsonResponse({'success': False, 'error': 'Retry failed - max retries exceeded'})
            else:
                return JsonResponse({'success': False, 'error': f'Cannot retry job in {job.status} status'})
        
        elif action == 'delete':
            if job.status in ['completed', 'failed', 'cancelled']:
                job.delete()
                return JsonResponse({'success': True, 'message': 'Job deleted'})
            else:
                return JsonResponse({'success': False, 'error': 'Cannot delete running job'})
        
        else:
            return JsonResponse({'success': False, 'error': f'Unknown action: {action}'})
            
    except Exception as e:
        logger.error(f"Job action error: {e}")
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def job_progress_ajax(request, job_id):
    """
    AJAX endpoint for getting live job progress.
    """
    try:
        job = get_object_or_404(DownloadJob, job_id=job_id)
        
        # Get live progress from downloader service
        downloader_service = get_downloader_service()
        live_progress = downloader_service.get_job_progress(job_id)
        
        # Sync job status
        downloader_service.sync_job_status(job)
        job.refresh_from_db()
        
        response_data = {
            'job_id': job.job_id,
            'status': job.status,
            'current_step': job.current_step,
            'total_steps': job.total_steps,
            'progress_percentage': job.progress_percentage,
            'current_message': job.current_message,
            'error_message': job.error_message,
            'live_progress': live_progress
        }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Progress AJAX error: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def system_status_ajax(request):
    """
    AJAX endpoint for getting system status.
    """
    try:
        downloader_service = get_downloader_service()
        system_status = downloader_service.get_system_status()
        
        # Add additional stats
        stats = {
            'total_jobs': DownloadJob.objects.count(),
            'active_jobs': DownloadJob.objects.filter(status__in=['pending', 'running']).count(),
            'completed_jobs': DownloadJob.objects.filter(status='completed').count(),
            'failed_jobs': DownloadJob.objects.filter(status='failed').count(),
            'unread_alerts': DownloadAlert.objects.filter(is_read=False).count()
        }
        
        return JsonResponse({
            'system_status': system_status,
            'stats': stats,
            'timestamp': timezone.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"System status AJAX error: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def bulk_job_action(request):
    """
    Handle bulk job actions.
    """
    if request.method == 'POST':
        try:
            job_ids = request.POST.getlist('job_ids')
            action = request.POST.get('action')
            
            if not job_ids or not action:
                messages.error(request, 'No jobs selected or action specified')
                return redirect('monitor:job_list')
            
            downloader_service = get_downloader_service()
            results = {'success': 0, 'failed': 0, 'skipped': 0}
            
            for job_id in job_ids:
                try:
                    job = DownloadJob.objects.get(job_id=job_id)
                    
                    if action == 'cancel':
                        if job.status in ['pending', 'running']:
                            success = downloader_service.cancel_job(job_id)
                            if success:
                                job.mark_cancelled()
                                results['success'] += 1
                            else:
                                results['failed'] += 1
                        else:
                            results['skipped'] += 1
                    
                    elif action == 'retry':
                        if job.status == 'failed':
                            success = downloader_service.retry_job(job_id)
                            if success:
                                results['success'] += 1
                            else:
                                results['failed'] += 1
                        else:
                            results['skipped'] += 1
                    
                    elif action == 'delete':
                        if job.status in ['completed', 'failed', 'cancelled']:
                            job.delete()
                            results['success'] += 1
                        else:
                            results['skipped'] += 1
                    
                except DownloadJob.DoesNotExist:
                    results['failed'] += 1
                except Exception as e:
                    logger.error(f"Bulk action error for job {job_id}: {e}")
                    results['failed'] += 1
            
            # Show results message
            message = f"Bulk {action}: {results['success']} successful, {results['failed']} failed, {results['skipped']} skipped"
            if results['failed'] > 0:
                messages.warning(request, message)
            else:
                messages.success(request, message)
            
            return redirect('monitor:job_list')
            
        except Exception as e:
            logger.error(f"Bulk action error: {e}")
            messages.error(request, f"Bulk action failed: {str(e)}")
            return redirect('monitor:job_list')
    
    return redirect('monitor:job_list')