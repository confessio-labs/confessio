from django.urls import path

from . import views
from .api import api
from .front_api import api as front_api
from django.contrib.auth import views as auth_views

urlpatterns = [
    # index
    path('', views.home, name='home'),
    path('index', views.index, name='index'),
    path('autocomplete', views.autocomplete, name='autocomplete'),
    path('website_events/<uuid:website_uuid>', views.partial_website_events,
         name='website_events'),
    path('website_churches/<uuid:website_uuid>', views.partial_website_churches,
         name='website_churches'),
    path('website_sources/<uuid:website_uuid>', views.partial_website_sources,
         name='website_sources'),
    path('dioceses', views.dioceses_list, name='dioceses_list'),
    path('diocese/<str:diocese_slug>', views.index, name='diocese_view'),
    path('around_place', views.index, name='around_place_view'),
    path('ville/<slug:city_slug>', views.index, name='city_view'),
    path('in_area', views.index, name='in_area_view'),
    path('around_me', views.index, {'is_around_me': True}, name='around_me_view'),
    path('paroisse/<uuid:website_uuid>', views.index, name='website_view'),
    path('paroisse/<uuid:website_uuid>/upload_image', views.website_upload_image,
         name='website_upload_image'),

    # Authentication
    path('accounts/login/', views.UserLoginView.as_view(), name='login'),
    path('accounts/logout/', views.logout_view, name='logout'),
    # path('accounts/register/', views.register, name='register'),
    path('accounts/password-change/', views.UserPasswordChangeView.as_view(),
         name='password_change'),
    path('accounts/password-change-done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='accounts/password_change_done.html'
    ), name='password_change_done'),
    path('accounts/password-reset/', views.UserPasswordResetView.as_view(),
         name='password_reset'),
    path('accounts/password-reset-done/', auth_views.PasswordResetDoneView.as_view(
        template_name='accounts/password_reset_done.html'
    ), name='password_reset_done'),
    path('accounts/password-reset-confirm/<uidb64>/<token>/',
         views.UserPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('accounts/password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='accounts/password_reset_complete.html'
    ), name='password_reset_complete'),

    # copilot (admin)
    path('copilot', views.copilot, name='copilot'),
    path('copilot/new', views.copilot_new, name='copilot_new'),
    path('copilot/<uuid:discussion_uuid>', views.copilot, name='copilot_view'),
    path('copilot/<uuid:discussion_uuid>/message', views.copilot_message, name='copilot_message'),
    path('copilot/<uuid:discussion_uuid>/approve', views.copilot_approve, name='copilot_approve'),
    path('copilot/<uuid:discussion_uuid>/items', views.copilot_items, name='copilot_items'),

    # moderation
    path('moderate', views.moderation_home, name='moderation_home'),
    path('moderate/report/<category>/<str:status>/<str:diocese_slug>',
         views.moderate_report, name='moderate_next_report'),
    path('moderate/report/<category>/<str:status>/<str:diocese_slug>/<uuid:moderation_uuid>',
         views.moderate_report, name='moderate_one_report'),

    # contact
    path('contact', views.contact, name='contact'),
    path('contact/<message>', views.contact, name='contact_success'),
    path('contact/<message>/<email>/<path:name_text>/<path:message_text>', views.contact,
         name='contact_failure'),
    path('about', views.about, name='about'),

    # webhooks
    path('webhooks/contact_mail', views.contact_mail_webhook, name='contact_mail_webhook'),

    # api
    path("api/", api.urls),
    path("front/api/", front_api.urls),
]
