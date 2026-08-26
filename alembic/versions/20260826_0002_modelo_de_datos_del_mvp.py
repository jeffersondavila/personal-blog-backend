"""modelo de datos del mvp

Revision: 0002
Revision anterior: 0001
Fecha de creacion: 2026-08-26 (UTC; `alembic.ini` fija `timezone = UTC`)

Primera migracion de negocio del proyecto. Crea el modelo fisico completo del MVP
descrito en `personal-blog-infra/docs/architecture/data-model.md`, que a su vez
materializa el modelo conceptual de `CONTENT_MODEL.md`.

Que crea
--------

Catorce tablas para los nueve tipos conceptuales del MVP, mas las cuatro tablas
puente de etiquetado y la tabla dependiente de enlaces sociales:

    administrators   audit_events        media_assets   profiles
    profile_social_links                 tags
    posts            book_reviews        videos         projects
    post_tags        book_review_tags    video_tags     project_tags

Que NO crea, y por que
----------------------

**Ningun dato.** No hay `INSERT` ni `bulk_insert` en este archivo, y no es un
descuido: el perfil y el administrador contienen datos personales reales —nombre,
correo, hash de contrasena— que no se versionan (requisito S-10). El esquema
garantiza que **como maximo** existe uno de cada; que exista **exactamente** uno
es trabajo del *bootstrap* del entorno, con datos que aporta su propietario.

**Ningun tipo `ENUM` nativo.** Los estados se guardan como `VARCHAR` con `CHECK`,
que se revierte sin dejar objetos sueltos en la base. Detalle y motivo en
`app/shared/database/types.py`.

Que exige el esquema al crear un borrador
-----------------------------------------

**Solo `title` y `slug`**, en los cuatro tipos publicables. Es lo unico que
USER_FLOWS.md B.2 proporciona en ese momento: el titulo lo escribe el
administrador y el slug lo propone la aplicacion. Todo lo demas admite nulo o
tiene un default **real** —`draft`, `false`, `''`, `'active'`, `'[]'`, `now()`—,
nunca un relleno para esquivar un `NOT NULL`.

Por eso `book_reviews.book_title`, `book_reviews.book_author`, `videos.provider`
y `videos.video_url` admiten nulo. Que un contenido **publicado** deba tenerlos
es una validacion de publicacion (B.7) y pertenece a `Task/012`. Regresion:
`tests/integration/test_borrador_minimo.py`.

Reversibilidad
--------------

`downgrade` deshace exactamente lo que `upgrade` creo, en orden inverso de
dependencias, y deja intacta la revision fundacional `0001`. El requisito M-04
lo comprueba de verdad en `tests/integration/test_migrations.py`, que ejecuta el
ciclo `upgrade` -> `downgrade` -> `upgrade` contra PostgreSQL real y compara el
esquema antes y despues.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('administrators',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('is_singleton', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failed_login_attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('failed_login_attempts >= 0', name=op.f('ck_administrators_intentos_no_negativos')),
    sa.CheckConstraint('is_singleton IS TRUE', name=op.f('ck_administrators_administrador_unico')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_administrators')),
    sa.UniqueConstraint('email', name=op.f('uq_administrators_email')),
    sa.UniqueConstraint('is_singleton', name=op.f('uq_administrators_is_singleton'))
    )
    op.create_table('media_assets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('object_key', sa.String(length=512), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('mime_type', sa.String(length=127), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('alt_text', sa.String(length=255), nullable=True),
    sa.Column('checksum', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('height IS NULL OR height > 0', name=op.f('ck_media_assets_alto_positivo')),
    sa.CheckConstraint('size_bytes > 0', name=op.f('ck_media_assets_tamano_positivo')),
    sa.CheckConstraint('width IS NULL OR width > 0', name=op.f('ck_media_assets_ancho_positivo')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_media_assets')),
    sa.UniqueConstraint('object_key', name=op.f('uq_media_assets_object_key'))
    )
    op.create_index(op.f('ix_media_assets_checksum'), 'media_assets', ['checksum'], unique=False)
    op.create_table('tags',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('slug', sa.String(length=160), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tags')),
    sa.UniqueConstraint('slug', name=op.f('uq_tags_slug'))
    )
    op.create_table('audit_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('entity_type', sa.String(length=64), nullable=False),
    sa.Column('entity_id', sa.Uuid(), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.ForeignKeyConstraint(['actor_id'], ['administrators.id'], name=op.f('fk_audit_events_actor_id_administrators'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events'))
    )
    op.create_index(op.f('ix_audit_events_actor_id'), 'audit_events', ['actor_id'], unique=False)
    op.create_index('ix_audit_events_entity_type_entity_id', 'audit_events', ['entity_type', 'entity_id'], unique=False)
    op.create_index('ix_audit_events_occurred_at', 'audit_events', ['occurred_at'], unique=False)
    op.create_index('ix_audit_events_request_id', 'audit_events', ['request_id'], unique=False)
    op.create_table('book_reviews',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('slug', sa.String(length=160), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('summary', sa.String(length=500), nullable=True),
    sa.Column('content', sa.Text(), server_default='', nullable=False),
    sa.Column('status', sa.Enum('draft', 'published', 'archived', name='book_review_status', native_enum=False, create_constraint=True, length=32), server_default='draft', nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('featured', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('book_title', sa.String(length=200), nullable=True),
    sa.Column('book_author', sa.String(length=200), nullable=True),
    sa.Column('rating', sa.SmallInteger(), nullable=True),
    sa.Column('external_link', sa.String(length=2048), nullable=True),
    sa.Column('cover_id', sa.Uuid(), nullable=True),
    sa.Column('seo_title', sa.String(length=70), nullable=True),
    sa.Column('seo_description', sa.String(length=160), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status <> 'published' OR published_at IS NOT NULL", name=op.f('ck_book_reviews_publicado_exige_fecha')),
    sa.CheckConstraint('rating >= 1 AND rating <= 5', name=op.f('ck_book_reviews_valoracion_en_escala')),
    sa.ForeignKeyConstraint(['cover_id'], ['media_assets.id'], name=op.f('fk_book_reviews_cover_id_media_assets'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_book_reviews')),
    sa.UniqueConstraint('slug', name=op.f('uq_book_reviews_slug'))
    )
    op.create_index(op.f('ix_book_reviews_cover_id'), 'book_reviews', ['cover_id'], unique=False)
    op.create_index('ix_book_reviews_status_published_at', 'book_reviews', ['status', 'published_at'], unique=False)
    op.create_table('posts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('slug', sa.String(length=160), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('summary', sa.String(length=500), nullable=True),
    sa.Column('content', sa.Text(), server_default='', nullable=False),
    sa.Column('status', sa.Enum('draft', 'published', 'archived', name='post_status', native_enum=False, create_constraint=True, length=32), server_default='draft', nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('featured', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('cover_id', sa.Uuid(), nullable=True),
    sa.Column('seo_title', sa.String(length=70), nullable=True),
    sa.Column('seo_description', sa.String(length=160), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status <> 'published' OR published_at IS NOT NULL", name=op.f('ck_posts_publicado_exige_fecha')),
    sa.ForeignKeyConstraint(['cover_id'], ['media_assets.id'], name=op.f('fk_posts_cover_id_media_assets'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_posts')),
    sa.UniqueConstraint('slug', name=op.f('uq_posts_slug'))
    )
    op.create_index(op.f('ix_posts_cover_id'), 'posts', ['cover_id'], unique=False)
    op.create_index('ix_posts_status_published_at', 'posts', ['status', 'published_at'], unique=False)
    op.create_table('profiles',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('is_singleton', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=False),
    sa.Column('headline', sa.String(length=200), nullable=True),
    sa.Column('biography', sa.Text(), server_default='', nullable=False),
    sa.Column('contact_email', sa.String(length=254), nullable=True),
    sa.Column('photo_id', sa.Uuid(), nullable=True),
    sa.Column('seo_title', sa.String(length=70), nullable=True),
    sa.Column('seo_description', sa.String(length=160), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('is_singleton IS TRUE', name=op.f('ck_profiles_perfil_unico')),
    sa.ForeignKeyConstraint(['photo_id'], ['media_assets.id'], name=op.f('fk_profiles_photo_id_media_assets'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_profiles')),
    sa.UniqueConstraint('is_singleton', name=op.f('uq_profiles_is_singleton'))
    )
    op.create_index(op.f('ix_profiles_photo_id'), 'profiles', ['photo_id'], unique=False)
    op.create_table('projects',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('slug', sa.String(length=160), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('summary', sa.String(length=500), nullable=True),
    sa.Column('content', sa.Text(), server_default='', nullable=False),
    sa.Column('status', sa.Enum('draft', 'published', 'archived', name='project_publication_status', native_enum=False, create_constraint=True, length=32), server_default='draft', nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('featured', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('project_status', sa.Enum('active', 'paused', 'completed', name='project_work_status', native_enum=False, create_constraint=True, length=32), server_default='active', nullable=False),
    sa.Column('technologies', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('repository_url', sa.String(length=2048), nullable=True),
    sa.Column('demo_url', sa.String(length=2048), nullable=True),
    sa.Column('cover_id', sa.Uuid(), nullable=True),
    sa.Column('seo_title', sa.String(length=70), nullable=True),
    sa.Column('seo_description', sa.String(length=160), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status <> 'published' OR published_at IS NOT NULL", name=op.f('ck_projects_publicado_exige_fecha')),
    sa.ForeignKeyConstraint(['cover_id'], ['media_assets.id'], name=op.f('fk_projects_cover_id_media_assets'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_projects')),
    sa.UniqueConstraint('slug', name=op.f('uq_projects_slug'))
    )
    op.create_index(op.f('ix_projects_cover_id'), 'projects', ['cover_id'], unique=False)
    op.create_index('ix_projects_status_published_at', 'projects', ['status', 'published_at'], unique=False)
    op.create_table('videos',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('slug', sa.String(length=160), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('summary', sa.String(length=500), nullable=True),
    sa.Column('status', sa.Enum('draft', 'published', 'archived', name='video_status', native_enum=False, create_constraint=True, length=32), server_default='draft', nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('featured', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=True),
    sa.Column('video_url', sa.String(length=2048), nullable=True),
    sa.Column('embed_reference', sa.String(length=255), nullable=True),
    sa.Column('duration_seconds', sa.Integer(), nullable=True),
    sa.Column('thumbnail_id', sa.Uuid(), nullable=True),
    sa.Column('seo_title', sa.String(length=70), nullable=True),
    sa.Column('seo_description', sa.String(length=160), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status <> 'published' OR published_at IS NOT NULL", name=op.f('ck_videos_publicado_exige_fecha')),
    sa.CheckConstraint('duration_seconds IS NULL OR duration_seconds > 0', name=op.f('ck_videos_duracion_positiva')),
    sa.ForeignKeyConstraint(['thumbnail_id'], ['media_assets.id'], name=op.f('fk_videos_thumbnail_id_media_assets'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_videos')),
    sa.UniqueConstraint('slug', name=op.f('uq_videos_slug'))
    )
    op.create_index('ix_videos_status_published_at', 'videos', ['status', 'published_at'], unique=False)
    op.create_index(op.f('ix_videos_thumbnail_id'), 'videos', ['thumbnail_id'], unique=False)
    op.create_table('book_review_tags',
    sa.Column('book_review_id', sa.Uuid(), nullable=False),
    sa.Column('tag_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['book_review_id'], ['book_reviews.id'], name=op.f('fk_book_review_tags_book_review_id_book_reviews'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], name=op.f('fk_book_review_tags_tag_id_tags'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('book_review_id', 'tag_id', name=op.f('pk_book_review_tags'))
    )
    op.create_index('ix_book_review_tags_tag_id', 'book_review_tags', ['tag_id'], unique=False)
    op.create_table('post_tags',
    sa.Column('post_id', sa.Uuid(), nullable=False),
    sa.Column('tag_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['post_id'], ['posts.id'], name=op.f('fk_post_tags_post_id_posts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], name=op.f('fk_post_tags_tag_id_tags'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('post_id', 'tag_id', name=op.f('pk_post_tags'))
    )
    op.create_index('ix_post_tags_tag_id', 'post_tags', ['tag_id'], unique=False)
    op.create_table('profile_social_links',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('profile_id', sa.Uuid(), nullable=False),
    sa.Column('label', sa.String(length=60), nullable=False),
    sa.Column('url', sa.String(length=2048), nullable=False),
    sa.Column('display_order', sa.SmallInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('display_order >= 0', name=op.f('ck_profile_social_links_orden_no_negativo')),
    sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], name=op.f('fk_profile_social_links_profile_id_profiles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_profile_social_links')),
    sa.UniqueConstraint('profile_id', 'display_order', name='uq_profile_social_links_profile_id_display_order')
    )
    op.create_index(op.f('ix_profile_social_links_profile_id'), 'profile_social_links', ['profile_id'], unique=False)
    op.create_table('project_tags',
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('tag_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_tags_project_id_projects'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], name=op.f('fk_project_tags_tag_id_tags'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('project_id', 'tag_id', name=op.f('pk_project_tags'))
    )
    op.create_index('ix_project_tags_tag_id', 'project_tags', ['tag_id'], unique=False)
    op.create_table('video_tags',
    sa.Column('video_id', sa.Uuid(), nullable=False),
    sa.Column('tag_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], name=op.f('fk_video_tags_tag_id_tags'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['video_id'], ['videos.id'], name=op.f('fk_video_tags_video_id_videos'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('video_id', 'tag_id', name=op.f('pk_video_tags'))
    )
    op.create_index('ix_video_tags_tag_id', 'video_tags', ['tag_id'], unique=False)

def downgrade() -> None:
    op.drop_index('ix_video_tags_tag_id', table_name='video_tags')
    op.drop_table('video_tags')
    op.drop_index('ix_project_tags_tag_id', table_name='project_tags')
    op.drop_table('project_tags')
    op.drop_index(op.f('ix_profile_social_links_profile_id'), table_name='profile_social_links')
    op.drop_table('profile_social_links')
    op.drop_index('ix_post_tags_tag_id', table_name='post_tags')
    op.drop_table('post_tags')
    op.drop_index('ix_book_review_tags_tag_id', table_name='book_review_tags')
    op.drop_table('book_review_tags')
    op.drop_index(op.f('ix_videos_thumbnail_id'), table_name='videos')
    op.drop_index('ix_videos_status_published_at', table_name='videos')
    op.drop_table('videos')
    op.drop_index('ix_projects_status_published_at', table_name='projects')
    op.drop_index(op.f('ix_projects_cover_id'), table_name='projects')
    op.drop_table('projects')
    op.drop_index(op.f('ix_profiles_photo_id'), table_name='profiles')
    op.drop_table('profiles')
    op.drop_index('ix_posts_status_published_at', table_name='posts')
    op.drop_index(op.f('ix_posts_cover_id'), table_name='posts')
    op.drop_table('posts')
    op.drop_index('ix_book_reviews_status_published_at', table_name='book_reviews')
    op.drop_index(op.f('ix_book_reviews_cover_id'), table_name='book_reviews')
    op.drop_table('book_reviews')
    op.drop_index('ix_audit_events_request_id', table_name='audit_events')
    op.drop_index('ix_audit_events_occurred_at', table_name='audit_events')
    op.drop_index('ix_audit_events_entity_type_entity_id', table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_actor_id'), table_name='audit_events')
    op.drop_table('audit_events')
    op.drop_table('tags')
    op.drop_index(op.f('ix_media_assets_checksum'), table_name='media_assets')
    op.drop_table('media_assets')
    op.drop_table('administrators')
